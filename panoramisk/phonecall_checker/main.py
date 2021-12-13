import asyncio
import panoramisk


AMI_CONNECTION_CONFIG = {
    'host': '192.168.50.41',
    'port': 5038,
    'username': 'username',
    'secret': 'secret'
}
AMI_CONNECTION_TIMEOUT = 3


async def work():
    ami_manager = panoramisk.Manager(**AMI_CONNECTION_CONFIG)

    print("Attempting AMI connection...")
    await asyncio.wait((ami_manager.connect(), ), return_when=asyncio.FIRST_COMPLETED)
    await asyncio.sleep(AMI_CONNECTION_TIMEOUT)
    if not ami_manager._connected:
        print("AMI connection attempt failed!")
        return
    else:
        print("AMI connection has been established!")

    interval = 5
    while True:
        print("Worker waits for %s seconds..." % interval)
        await asyncio.sleep(interval)
        print("Worker doing some work")


def main():
    print("Phonecall checker started!")
    loop = asyncio.get_event_loop()
    task = loop.create_task(work())
    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        task.cancel()
    loop.stop()
    print("Phonecall checker finished!")


if __name__ == '__main__':
    main()
