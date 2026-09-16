# AR-03 跨实例 / 跨仓库状态串档

- **TP 必须命中**：状态常量是仓库外的绝对路径；目标常量硬编码（tp.py）
- **TP2 必须命中**：换一组常量名（STATE_FILE / WORKDIR）同样命中（tp2.py）
- **FP 必须不命中**：路径由 `os.path.join` / 环境变量拼出，已参数化（fp.py）
- **FP2 必须不命中**：同义写法但走 `expanduser` + 环境变量（fp2.py）

判据只看「是不是写死的绝对路径」；表达式赋值一律放过——那说明已可配置。

实测来源：某推送工具 `STATE_PATH = "/data/workspace/.push-sync.json"`（在被操作仓库之外），
配合 `OWNER, REPO = "...", "tauriTools"`；而该文件所在仓库叫 `push-api-tools`。
