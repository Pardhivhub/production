import asyncio

class LogStreamer:
    def __init__(self):
        self.queues = []

    async def broadcast(self, message: str):
        for q in self.queues:
            await q.put(message)

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self.queues:
            self.queues.remove(q)

log_streamer = LogStreamer()
