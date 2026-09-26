import traceback
from typing import Optional, Union, Dict, List

from pymilvus import MilvusClient, CollectionSchema
from starlette.concurrency import run_in_threadpool

from utils.logger import get_logger

logger = get_logger()


class Milvus_utils:
    def __init__(self, milvus_cfg):
        self.milvus_cfg = milvus_cfg
        self.uri = self.milvus_cfg['uri']
        self.user = self.milvus_cfg['user']
        self.password = self.milvus_cfg['password']
        self.db_name = self.milvus_cfg['db_name']

        self.client = None

    def connect(self):
        """延迟连接到 Milvus 服务"""
        if self.client is None:
            try:
                self.client = MilvusClientUtils(
                    uri=self.uri,
                    token=f"{self.user}:{self.password}",
                    db_name=self.db_name
                )
                logger.info("Milvus client connected.")
            except Exception as e:
                logger.error(f"Failed to connect to Milvus: {e}")
                self.client = None  # 连接失败，保持为 None
        return self.client

    def ensure_connected(self):
        """确保连接已建立，若没有连接尝试重连"""
        if self.client is None:
            self.connect()

    def close(self):
        if self.client:
            self.client.close()


class MilvusClientUtils(MilvusClient):
    def __init__(self, uri=None, token=None, db_name: str = "", **kwargs):
        super().__init__(uri=uri, token=token, db_name=db_name, **kwargs)

    async def create_collection_async(self, collection_name: str,
                                      dimension: Optional[int],
                                      primary_field_name: str = "id",  # default is "id"
                                      id_type: str = "int",  # or "string",
                                      vector_field_name: str = "vector",  # default is  "vector"
                                      metric_type: str = "COSINE",
                                      auto_id: bool = False,
                                      timeout: Optional[float] = None,
                                      schema: Optional[CollectionSchema] = None, **kwargs):
        return await run_in_threadpool(super().create_collection, collection_name,
                                       dimension, primary_field_name, id_type,
                                       vector_field_name, metric_type, auto_id,
                                       timeout, schema, **kwargs)

    async def create_partition_async(self, collection_name: str,
                                     partition_name: str,
                                     timeout: Optional[float] = None, **kwargs):
        return await run_in_threadpool(super().create_partition, collection_name,
                                       partition_name, timeout, **kwargs)

    async def insert_data_async(self, collection_name: str,
                                data: Union[Dict, List[Dict]],
                                timeout: Optional[float] = None,
                                partition_name: Optional[str] = "", **kwargs):
        return await run_in_threadpool(super().insert, collection_name, data, timeout, partition_name, **kwargs)

    async def list_partitions_async(self, collection_name: str, timeout: Optional[float] = None, **kwargs):
        return await run_in_threadpool(super().list_partitions, collection_name=collection_name, timeout=timeout,
                                       **kwargs)

    async def insert_data_api(self, collection_name: str, partition_name: str, data: list = None):
        try:
            # 存储文件向量信息
            # 创建分区
            partitions_list = await self.list_partitions_async(collection_name=collection_name)
            if partition_name not in partitions_list:
                await self.create_partition_async(collection_name=collection_name, partition_name=partition_name)
            # 写入数据
            res = await self.insert_data_async(collection_name=collection_name, data=data,
                                               partition_name=partition_name)
            if res:
                logger.info(res)
                return True
        except Exception as e:
            logger.error(traceback.format_exc())
        return False




