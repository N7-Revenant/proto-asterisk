import asyncio
import logging
import panoramisk
import time


AMI_EVENT_NAME_ORIGINATE_RESPONSE = 'OriginateResponse'
AMI_EVENT_NAME_STATUS = 'Status'
AMI_EVENT_NAME_HANGUP = 'Hangup'


class EnhancedManager(panoramisk.Manager):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def connected(self):
        return self._connected


class EnhancedAction(panoramisk.manager.actions.Action):
    def add_message(self, message):
        self.responses.append(message)
        if not self.future.done():
            self.future.set_result(self.responses[0])
        return True

    def __delitem__(self, key):
        raise NotImplementedError()


class ActionGenerator:
    __BASE_ORIGINATE_PARAMS = {
        'Action': 'Originate',
        'Context': 'handler',
        'Priority': 1,
        'Async': True
    }

    __BASE_STATUS_PARAMS = {
        'Action': 'Status'
    }

    @staticmethod
    def generate_originate_action(callee: str, caller: str, timeout_ms: int) -> EnhancedAction:
        originate_params = dict()
        originate_params.update(ActionGenerator.__BASE_ORIGINATE_PARAMS)
        originate_params.update({
            'CallerID': '%s' % caller,
            'Channel': 'Local/%s@origin' % callee,
            'Exten': '%s' % caller,
            'Timeout': timeout_ms
        })
        return EnhancedAction(originate_params)

    @staticmethod
    def generate_status_action(channel: str) -> EnhancedAction:
        status_params = dict()
        status_params.update(ActionGenerator.__BASE_STATUS_PARAMS)
        status_params.update({
            'Channel': channel
        })
        return EnhancedAction(status_params)


class PhonecallContext:
    def __init__(self, unique_id: str, channel_name: str):
        self.__unique_id = unique_id
        self.__channel_name = channel_name

        self.__phonecall_completed = asyncio.Event()

        self.__ts_last_activity = time.time()
        self.__ts_last_status_request = 0

    def uphold(self):
        self.__ts_last_activity = time.time()

    def check_activity_required(self, max_idle_time: float) -> bool:
        return time.time() - self.__ts_last_activity > max_idle_time

    def check_status_request_allowed(self, request_interval: float) -> bool:
        return time.time() - self.__ts_last_status_request > request_interval

    def status_requested(self):
        self.__ts_last_status_request = time.time()

    def close(self):
        self.__phonecall_completed.set()

    @property
    def unique_id(self):
        return self.__unique_id

    @property
    def channel_name(self):
        return self.__channel_name

    @property
    def completion_event(self) -> asyncio.Event:
        return self.__phonecall_completed

    @property
    def completed(self) -> bool:
        return self.__phonecall_completed.is_set()


class PhonecallController:
    def __init__(self, manager: EnhancedManager, logger: logging.Logger,
                 interval_check: float = 1., interval_uphold: float = 3., interval_status_request: float = 5.):
        self.__manager = manager
        self.__logger = logger

        self.__interval_check = interval_check
        self.__interval_uphold = interval_uphold
        self.__interval_status_request = interval_status_request

        self.__manager.register_event('*', lambda _, event: self.handle_ami_event(event))

        self.__phonecall_initiations = set()
        self.__phonecall_contexts = dict()
        self.__phonecall_checker_task = None

    async def __check_phonecall_contexts(self):
        self.__logger.info("Phonecall checker task started!")
        try:
            while True:
                await asyncio.sleep(self.__interval_check)
                for context in self.__phonecall_contexts.values():  # type: PhonecallContext
                    if (not context.completed
                            and context.check_activity_required(self.__interval_uphold)
                            and context.check_status_request_allowed(self.__interval_status_request)):
                        result: panoramisk.Message = await self.__manager.send_action(
                            ActionGenerator.generate_status_action(channel=context.channel_name))
                        self.__logger.debug("Channel check result: %s", result)
                        context.status_requested()
                        if not result.success:
                            context.close()
                            self.__logger.info(
                                "Phonecall context with UniqueID '%s' has been closed on Channel check fail!",
                                context.unique_id)

        except asyncio.CancelledError:
            self.__logger.info("Phonecall checker task stopped!")

        except Exception as exc:
            self.__logger.error("Phonecall checker task failed with error: %s", exc, exc_info=exc)

    def handle_ami_event(self, message: panoramisk.Message):
        self.__logger.debug(message)
        event_name = message.get('Event')
        unique_id = message.get('Uniqueid')
        channel_name = message.get('Channel')

        if event_name == AMI_EVENT_NAME_ORIGINATE_RESPONSE:
            action_id = message.get('ActionID')
            self.__phonecall_initiations.discard(action_id)

            if unique_id == '<null>':
                self.__logger.warning(
                    "Phonecall context is not created on '%s' Event - UniqueID is empty: %s!",
                    event_name, message)

            else:
                self.__phonecall_contexts[unique_id] = PhonecallContext(unique_id=unique_id, channel_name=channel_name)
                self.__logger.info(
                    "Phonecall context with UniqueID '%s' has been created on '%s' Event!",
                    unique_id, event_name)

        elif event_name == AMI_EVENT_NAME_HANGUP:
            context: PhonecallContext = self.__phonecall_contexts.get(unique_id)
            if context is not None:
                context.close()
                self.__logger.info(
                    "Phonecall context with UniqueID '%s' has been closed on '%s' Event!",
                    unique_id, event_name)

        else:
            context: PhonecallContext = self.__phonecall_contexts.get(unique_id)
            if context is not None:
                context.uphold()
                self.__logger.info(
                    "Phonecall context with UniqueID '%s' upheld on '%s' Event!",
                    unique_id, event_name)

    async def initiate_ami_connection(self):
        await asyncio.wait((self.__manager.connect(),), return_when=asyncio.FIRST_COMPLETED)
        self.__phonecall_checker_task = asyncio.get_running_loop().create_task(self.__check_phonecall_contexts())

    @property
    def ami_connected(self):
        return self.__manager.connected

    @property
    def active_phonecalls(self):
        result = list()
        for unique_id in self.__phonecall_contexts:
            if not self.__phonecall_contexts[unique_id].completion_event.is_set():
                result.append(unique_id)
        return result

    async def wait_completion(self, unique_id):
        if unique_id in self.__phonecall_contexts:
            await self.__phonecall_contexts[unique_id].completion_event.wait()

    async def attempt_phonecall_initiation(self, caller: str, callee: str, initiation_timeout_ms: int):
        if self.__manager.connected:
            action_originate = ActionGenerator.generate_originate_action(callee=callee, caller=caller,
                                                                         timeout_ms=initiation_timeout_ms)
            initiation_result: panoramisk.Message = await self.__manager.send_action(action_originate)
            if not initiation_result.success:
                self.__logger.error("Phonecall initiation failed: %s", initiation_result.get('Message'))
            else:
                self.__phonecall_initiations.add(action_originate.id)
            return initiation_result.success

        else:
            self.__logger.error("Phonecall initiation failed: AMI connection is missing!")
            return False

    @property
    def initiating_phonecalls(self):
        return tuple(self.__phonecall_initiations)

    def discard_ami_connection(self):
        if isinstance(self.__phonecall_checker_task, asyncio.Task):
            self.__phonecall_checker_task.cancel()
        self.__manager.close()
