"""Retriever Query Engine."""

from typing import Optional, List, cast
from langflow import CustomComponent
from langflow.utils.util import build_loader_repr_from_documents
from llama_index.schema import Document, TextNode
from llama_index.node_parser import SentenceSplitter
from llama_index import VectorStoreIndex, ServiceContext
from langflow.field_typing import Object, BaseLanguageModel
from llama_index.retrievers import VectorIndexRetriever
from llama_index.query_engine import RetrieverQueryEngine
from llama_index.llms import LangChainLLM


class RetrieverQueryEngineComponent(CustomComponent):
    display_name: str = "Retriever Query Engine" 
    description: str = "Builds a query engine"
    
    def build_config(self):
        return {
            "retriever": {
                "display_name": "Retriever",
                "info": "The retriever to use",
            },
            "response_mode": {
                "display_name": "Response Mode",
                "info": "Mode to use for synthesizing a response",
                "field_type": "str",
            },
            "llm": {
                "display_name": "LLM",
                "info": "The LLM to use (use LangChain LLM)",
            }
        }
    
    def build(
        self,
        retriever: Object,
        llm: BaseLanguageModel,
        response_mode: str = "compact",
    ) -> Object:
        """Build."""
        retriever = cast(VectorIndexRetriever, retriever)
        llm_wrapper = LangChainLLM(llm)
        service_context = ServiceContext.from_defaults(llm_wrapper)
        # return Callable
        query_engine = RetrieverQueryEngine.from_args(
            retriever,
            response_mode=response_mode,
            service_context=service_context,
        )
        return query_engine
