from langchain_community.utilities import SearxSearchWrapper
from langchain_community.tools.searx_search.tool import SearxSearchResults
from abc import ABC, abstractmethod
from langchain_community.tools.tavily_search import TavilySearchResults
import os


class BaseSearchTool(ABC):
    @abstractmethod
    def get_searh_tool(self):
        """
        获取搜索工具
        """
        pass

class SearxSearchTool(BaseSearchTool):
    def __init__(self,
                 searx_host: str,
                 ):
        search_wrapper = SearxSearchWrapper(
            searx_host=searx_host,
        )
        
        self.search_tool = SearxSearchResults(wrapper=search_wrapper,
                            kwargs = {
                                "engines": ["ask", "360search", "alexandria", "wikisource","bing","baidu"],
                                "max_results": 10,
                                })

    def get_searh_tool(self):
        return self.search_tool


class TavilySearchTool(BaseSearchTool):
    def __init__(self,
                 tavily_api_key: str,
                 ):
        os.environ["TAVILY_API_KEY"] = tavily_api_key
        self.search_tool = TavilySearchResults()
        
    def get_searh_tool(self):
        return self.search_tool
        
        