from AquaAgent import aqua_config

from AquaAgent.agent import SystemOperationAgent

aqua_config.load_config('config/cloud.yaml')


agent = SystemOperationAgent()


agent.chat()
# 卸载lightgdm界面，换成ubuntu默认的gonme





