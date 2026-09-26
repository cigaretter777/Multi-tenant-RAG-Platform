from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter

from configs.config import *


def retrieve_for_phish(index, question, template_type, similarity_top_k):
    '''
    查询问题
    index:索引
    question:问题
    return 查询结果
    '''

    filter = MetadataFilters(filters=[ExactMatchFilter(key="template_type", value=template_type)])

    index_ret = index.as_retriever(similarity_top_k=similarity_top_k, filters=filter)

    logger.info("检索中...")
    retriever_result = index_ret.retrieve(question)
    logger.info(f'检索结果： {retriever_result}')

    return retriever_result
