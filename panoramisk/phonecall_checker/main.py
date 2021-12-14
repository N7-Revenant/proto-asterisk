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

ORIGINATE_SETTINGS = {
    'Action': 'Originate',
    'Channel': 'Local/1000@origin',
    'WaitTime': 20,
    'CallerID': 'username',
    'Context': 'handler',
    'Exten': '1000',
    'Priority': 1,
    'Async': True
}


class ActionOriginate(panoramisk.actions.Action):
    def add_message(self, message):
        self.responses.append(message)
        if not self.future.done():
            self.future.set_result(self.responses[0])
        return True


def handle_ami_event(message: panoramisk.Message):
    log.info(message)


async def work():
    ami_manager = panoramisk.Manager(**AMI_CONNECTION_CONFIG)

    log.info("Attempting AMI connection...")
    await asyncio.wait((ami_manager.connect(), ), return_when=asyncio.FIRST_COMPLETED)
    await asyncio.sleep(AMI_CONNECTION_TIMEOUT)
    if not ami_manager._connected:
        log.error("AMI connection attempt failed!")
        return
    else:
        log.info("AMI connection has been established!")

    for ami_event in AMI_EVENTS:
        ami_manager.register_event(ami_event, lambda _, event: handle_ami_event(event))

    log.info("Initiating new phonecall...")
    action_originate = ActionOriginate(ORIGINATE_SETTINGS)
    initiation_result: panoramisk.Message = await ami_manager.send_action(action_originate)
    if not initiation_result.success:
        log.error("Phonecall initiation failed: %s", initiation_result.get('Message'))
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
