import asyncio
import logging
import panoramisk
import sys


log = logging.getLogger()

AMI_CONNECTION_CONFIG = {
    'host': '192.168.50.41',
    'port': 5038,
    'username': 'username',
    'secret': 'secret'
}
AMI_CONNECTION_TIMEOUT = 3

AMI_EVENTS = ('OriginateResponse', 'Hangup')


class EnhancedManager(panoramisk.Manager):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def connected(self):
        return self._connected


class ActionOriginate(panoramisk.actions.Action):
    def add_message(self, message):
        self.responses.append(message)
        if not self.future.done():
            self.future.set_result(self.responses[0])
        return True


class OriginateGenerator:
    __BASE_COMMAND = {
        'Action': 'Originate',
        'WaitTime': 20,
        'CallerID': 'username',
        'Context': 'handler',
        'Priority': 1,
        'Async': True
    }

    @staticmethod
    def generate_originate_action(callee: str, caller: str) -> ActionOriginate:
        originate_params = dict()
        originate_params.update(OriginateGenerator.__BASE_COMMAND)
        originate_params.update({
            'Channel': 'Local/%s@origin' % callee,
            'Exten': '%s' % caller,
        })
        return ActionOriginate(originate_params)


class PhonecallController:
    def __init__(self):
        self.__manager = EnhancedManager(**AMI_CONNECTION_CONFIG)

        for ami_event in AMI_EVENTS:
            self.__manager.register_event(ami_event, lambda _, event: self.handle_ami_event(event))

    @staticmethod
    def handle_ami_event(message: panoramisk.Message):
        log.info(message)

    async def initiate_ami_connection(self):
        await asyncio.wait((self.__manager.connect(),), return_when=asyncio.FIRST_COMPLETED)

    @property
    def ami_connected(self):
        return self.__manager.connected

    async def attempt_phonecall_initiation(self, caller: str = '1000', callee: str = '1000'):
        action_originate = OriginateGenerator.generate_originate_action(callee=callee, caller=caller)
        initiation_result: panoramisk.Message = await self.__manager.send_action(action_originate)
        if not initiation_result.success:
            log.error("Phonecall initiation failed: %s", initiation_result.get('Message'))
        return initiation_result.success

    @property
    def ami_manager(self):
        return self.__manager

    async def discard_ami_connection(self):
        await self.__manager.close()


async def work():
    controller = PhonecallController()

    log.info("Attempting AMI connection...")
    await controller.initiate_ami_connection()
    await asyncio.sleep(AMI_CONNECTION_TIMEOUT)
    if not controller.ami_connected:
        log.error("AMI connection attempt failed!")
        await controller.discard_ami_connection()
        return
    else:
        log.info("AMI connection has been established!")

    log.info("Initiating new phonecall...")
    phonecall_initiated = await controller.attempt_phonecall_initiation(caller='1000', callee='1000')
    if not phonecall_initiated:
        log.error("Unable to initiate phonecall!")
        await controller.discard_ami_connection()
        return
    else:
        log.info("New phonecall successfully initiated!")

    interval = 5
    while True:
        await asyncio.sleep(interval)
        log.warning("Phonecall state checking is not implemented!")
        # TODO: Add phonecall state checking


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
