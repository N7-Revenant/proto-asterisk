import asyncio


async def work():
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
        loop.run_forever()
    except KeyboardInterrupt:
        task.cancel()
    loop.stop()
    print("Phonecall checker finished!")


if __name__ == '__main__':
    main()
