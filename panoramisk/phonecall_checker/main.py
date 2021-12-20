import asyncio
import logging
import panoramisk
import sys
import time


log = logging.getLogger()

INVALID_PARAM = '000'

CALLER = '1000'
CALLEES = [
    '000',  # Error in phonecall
    '1000',  # Rejected phonecall
    '3000',  # Unanswered phonecall
    '4000'  # Answered phonecall
]

AMI_CONNECTION_CONFIG = {
    'host': '192.168.50.41',
    'port': 5038,
    # 'username': 'username',  # AMI User with correct events
    'username': 'hangupless',  # AMI User without "Hangup" event
    'secret': 'secret'
}

INTERVAL_PHONECALL_CHECK = 1.
INTERVAL_PHONECALL_CONTEXT_UPHOLD = 3.
INTERVAL_PHONECALL_STATUS_REQUEST = 5.

AMI_EVENT_NAME_ORIGINATE_RESPONSE = 'OriginateResponse'
AMI_EVENT_NAME_STATUS = 'Status'
AMI_EVENT_NAME_HANGUP = 'Hangup'


class EnhancedManager(panoramisk.Manager):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def connected(self):
        return self._connected


class EnhancedAction(panoramisk.actions.Action):
    def add_message(self, message):
        self.responses.append(message)
        if not self.future.done():
            self.future.set_result(self.responses[0])
        return True


class ActionGenerator:
    __BASE_ORIGINATE_PARAMS = {
        'Action': 'Originate',
        'Timeout': 5000,
        'CallerID': 'username',
        'Context': 'handler',
        'Priority': 1,
        'Async': True
    }

    __BASE_STATUS_PARAMS = {
        'Action': 'Status'
    }

    @staticmethod
    def generate_originate_action(callee: str, caller: str) -> EnhancedAction:
        originate_params = dict()
        originate_params.update(ActionGenerator.__BASE_ORIGINATE_PARAMS)
        originate_params.update({
            'Channel': 'Local/%s@origin' % callee,
            'Exten': '%s' % caller,
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
    def __init__(self):
        self.__manager = EnhancedManager(**AMI_CONNECTION_CONFIG)

        self.__manager.register_event('*', lambda _, event: self.handle_ami_event(event))

        self.__phonecall_contexts = dict()
        self.__phonecall_checker_task = None

    async def __check_phonecall_contexts(self):
        log.info("Phonecall checker task started!")
        try:
            while True:
                await asyncio.sleep(INTERVAL_PHONECALL_CHECK)
                for context in self.__phonecall_contexts.values():  # type: PhonecallContext
                    if (not context.completed
                            and context.check_activity_required(INTERVAL_PHONECALL_CONTEXT_UPHOLD)
                            and context.check_status_request_allowed(INTERVAL_PHONECALL_STATUS_REQUEST)):
                        result: panoramisk.Message = await self.__manager.send_action(
                            ActionGenerator.generate_status_action(channel=context.channel_name))
                        log.debug("Channel check result: %s", result)
                        context.status_requested()
                        if not result.success:
                            context.close()
                            log.info("Phonecall context with UniqueID '%s' has been closed on Channel check fail!",
                                     context.unique_id)

        except asyncio.CancelledError:
            log.info("Phonecall checker task stopped!")

        except Exception as exc:
            log.error("Phonecall checker task failed with error: %s", exc, exc_info=exc)

    def handle_ami_event(self, message: panoramisk.Message):
        log.debug(message)
        event_name = message.get('Event')
        unique_id = message.get('Uniqueid')
        channel_name = message.get('Channel')

        if event_name == AMI_EVENT_NAME_ORIGINATE_RESPONSE:
            if unique_id == '<null>':
                log.warning("Phonecall context is not created on '%s' Event - UniqueID is empty: %s!",
                            event_name, message)

            else:
                self.__phonecall_contexts[unique_id] = PhonecallContext(unique_id=unique_id, channel_name=channel_name)
                log.info("Phonecall context with UniqueID '%s' has been created on '%s' Event!",
                         unique_id, event_name)

        elif event_name == AMI_EVENT_NAME_HANGUP:
            context: PhonecallContext = self.__phonecall_contexts.get(unique_id)
            if context is not None:
                context.close()
                log.info("Phonecall context with UniqueID '%s' has been closed on '%s' Event!",
                         unique_id, event_name)

        else:
            context: PhonecallContext = self.__phonecall_contexts.get(unique_id)
            if context is not None:
                context.uphold()
                log.info("Phonecall context with UniqueID '%s' uphold on '%s' Event!",
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

    async def attempt_phonecall_initiation(self, caller: str, callee: str):
        if self.__manager.connected:
            action_originate = ActionGenerator.generate_originate_action(callee=callee, caller=caller)
            initiation_result: panoramisk.Message = await self.__manager.send_action(action_originate)
            if not initiation_result.success:
                log.error("Phonecall initiation failed: %s", initiation_result.get('Message'))
            return initiation_result.success

        else:
            log.error("Phonecall initiation failed: AMI connection is missing!")
            return False

    def discard_ami_connection(self):
        if isinstance(self.__phonecall_checker_task, asyncio.Task):
            self.__phonecall_checker_task.cancel()
        self.__manager.close()


async def wait_phonecalls_completion(controller: PhonecallController, count: int):
    tracked_phonecalls = set()
    loop = asyncio.get_running_loop()

    while len(tracked_phonecalls) < count:
        await asyncio.sleep(INTERVAL_PHONECALL_CHECK)
        phonecall_ids = controller.active_phonecalls
        if len(phonecall_ids) > 0:
            tracked_phonecalls.update(phonecall_ids)
    else:
        log.info("Waiting for phonecalls %s to finish...", tracked_phonecalls)

    tasks = list()
    for uid in tracked_phonecalls:
        task = loop.create_task(controller.wait_completion(unique_id=uid))
        tasks.append(task)

    await asyncio.wait(tasks)
    log.info("All tracked phonecalls %s are finished!", tracked_phonecalls)


async def work():
    controller = PhonecallController()

    log.info("Initiating AMI connection...")
    await controller.initiate_ami_connection()

    # Attempting phonecall initiation with invalid params
    await controller.attempt_phonecall_initiation(caller=INVALID_PARAM, callee=INVALID_PARAM)

    # Attempting phonecall initiation with valid params
    log.info("Initiating new phonecall...")
    some_phonecall_initiated = False
    for callee in CALLEES:
        initiation_outcome = await controller.attempt_phonecall_initiation(caller=CALLER, callee=callee)
        if not some_phonecall_initiated:
            some_phonecall_initiated = initiation_outcome

    if not some_phonecall_initiated:
        log.error("Unable to initiate phonecalls!")

    else:
        log.info("New phonecall successfully initiated!")
        await wait_phonecalls_completion(controller=controller, count=1)

    controller.discard_ami_connection()


def main():
    log.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    log.addHandler(handler)

    log.info("Phonecall checker started!")
    loop = asyncio.get_event_loop()
    task = loop.create_task(work())
    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        task.cancel()
    loop.stop()
    log.info("Phonecall checker finished!")


if __name__ == '__main__':
    main()
