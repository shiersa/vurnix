# fixtures/ 下的 test_*.py 是被测数据（弱化样例、语法错样例等），不是本仓测试，
# 禁止 pytest 收集（否则语法错夹具会炸掉收集期）。
collect_ignore = ["fixtures"]
