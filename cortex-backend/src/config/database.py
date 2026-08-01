import structlog
from neo4j import AsyncGraphDatabase, AsyncDriver

logger = structlog.get_logger(__name__)


class Neo4jDriver:
    def __init__(self):
        self._driver: AsyncDriver | None = None
        self._database: str = "neo4j"

    async def connect(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        self._database = database
        await self._driver.verify_connectivity()
        logger.info("neo4j_connected", uri=uri, database=database)

    async def disconnect(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("neo4j_disconnected")

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError("Neo4j driver not initialized. Call connect() first.")
        return self._driver

    async def execute_read(self, query: str, parameters: dict | None = None) -> list:
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, parameters or {})
            return [record.data() async for record in result]

    async def execute_write(self, query: str, parameters: dict | None = None) -> list:
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, parameters or {})
            return [record.data() async for record in result]


neo4j_driver = Neo4jDriver()
