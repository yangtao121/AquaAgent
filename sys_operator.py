from AquaAgent import aqua_config

from AquaAgent.agent import SystemOperationAgent

aqua_config.load_config('config/cloud.yaml')


agent = SystemOperationAgent()


agent.chat()
# 在这台电脑上部署ragflow，注意小心操作, 参考网站https://github.com/infiniflow/ragflow，需要关闭什么服务，端口冲突错误，不要自行处理





