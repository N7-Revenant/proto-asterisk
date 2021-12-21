import asyncio
import logging
import sys

from phonecalls import EnhancedManager, PhonecallController


log = logging.getLogger()

PHONECALL_INITIATION_TIMEOUT_MS = 3000
PHONECALL_PARTICIPANTS = [
    ('000', '000'),     # Incorrect params
    ('1000', '000'),    # Error in phonecall
    ('1000', '1000'),   # Rejected phonecall
    ('1000', '3000'),   # Unanswered phonecall
    ('1000', '4000'),   # Answered phonecall
    ('1000', '4001'),   # Answered phonecall
    ('1000', '4002')    # Answered phonecall
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


async def wait_phonecalls_completion(controller: PhonecallController):
    tracked_phonecalls = set()
    loop = asyncio.get_running_loop()

    while len(controller.initiating_phonecalls) > 0:
        log.info("Waiting for '%s' phonecall(s) %s to be initiated...",
                 len(controller.initiating_phonecalls), controller.initiating_phonecalls)
        await asyncio.sleep(INTERVAL_PHONECALL_CHECK)

    else:
        phonecall_ids = controller.active_phonecalls
        if len(phonecall_ids) > 0:
            tracked_phonecalls.update(phonecall_ids)

    log.info("Tracking phonecall context(s): %s", tracked_phonecalls)
    log.info("Waiting for '%s' phonecall(s) to finish...", len(tracked_phonecalls))

    tasks = list()
    for uid in tracked_phonecalls:
        task = loop.create_task(controller.wait_completion(unique_id=uid))
        tasks.append(task)

    await asyncio.wait(tasks)
    log.info("All tracked phonecalls %s are finished!", tracked_phonecalls)


async def work():
    ami_manager = EnhancedManager(**AMI_CONNECTION_CONFIG)

    controller = PhonecallController(manager=ami_manager, logger=log, interval_check=INTERVAL_PHONECALL_CHECK,
                                     interval_uphold=INTERVAL_PHONECALL_CONTEXT_UPHOLD,
                                     interval_status_request=INTERVAL_PHONECALL_STATUS_REQUEST)

    log.info("Initiating AMI connection...")
    await controller.initiate_ami_connection()

    log.info("Initiating new phonecall...")
    some_phonecall_initiated = False
    for caller, callee in PHONECALL_PARTICIPANTS:
        initiation_outcome = await controller.attempt_phonecall_initiation(
            caller=caller, callee=callee, initiation_timeout_ms=PHONECALL_INITIATION_TIMEOUT_MS)
        if not some_phonecall_initiated:
            some_phonecall_initiated = initiation_outcome

    if not some_phonecall_initiated:
        log.error("Unable to initiate phonecalls!")

    else:
        log.info("New phonecall successfully initiated!")
        await wait_phonecalls_completion(controller=controller)

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
