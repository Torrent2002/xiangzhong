#!/usr/bin/env bash
# 相中 demo · 国内云服务器一键部署（Ubuntu/Debian）
# 用法：git clone 本仓库 → cd 进仓库 → bash deploy.sh
# 完成后访问 http://<服务器公网IP>:8000
set -e

cd "$(dirname "$0")/demo"
DEMO_DIR="$(pwd)"

echo ">>> 1/4 装系统依赖（python3 / venv）"
command -v python3 >/dev/null 2>&1 || sudo apt-get install -y -qq python3
# Ubuntu 的 python3 自带 venv 模块但不含 ensurepip（需单独装 python3-venv），
# 用 import ensurepip 探测才准；漏装会导致 python3 -m venv 失败。
if ! python3 -c "import ensurepip" 2>/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv
fi

echo ">>> 2/4 建 venv + 装依赖（清华镜像，国内快）"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
./.venv/bin/pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

echo ">>> 3/4 检查 .env（你的豆包 key）"
if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "⚠️  已从模板创建 $DEMO_DIR/.env，但还没填 key。请编辑："
  echo "    nano $DEMO_DIR/.env     （不熟 nano 就用 vi）"
  echo "  把这几项从你本地 .env 抄过来填上："
  echo "    OPENAI_API_KEY / OPENAI_BASE_URL / MODEL / VISION_MODEL"
  echo "  填完再跑一次：bash $(dirname "$DEMO_DIR")/deploy.sh"
  echo
  exit 0
fi

echo ">>> 4/4 启动 app（绑 0.0.0.0:8000，后台跑）"
pkill -f "venv/bin/python app.py" 2>/dev/null || true
sleep 1
nohup ./.venv/bin/python app.py > app.log 2>&1 &
echo "✅ 已启动 PID=$!"
sleep 3
echo "--- 启动日志（尾部）---"
tail -6 app.log

echo
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null | grep -q 200; then
  echo "✅ 本机自检：8000 正常"
else
  echo "⚠️  本机 8000 没起来，看日志：tail -f $DEMO_DIR/app.log"
fi

echo
echo "=========================================="
echo "  访问：http://<服务器公网IP>:8000"
echo "  看日志：tail -f $DEMO_DIR/app.log"
echo "  停止：  pkill -f 'venv/bin/python app.py'"
echo "  重启：  bash $(dirname "$DEMO_DIR")/deploy.sh"
echo "  ⚠️ 别忘了在云控制台开放 8000 端口（安全组/防火墙）"
echo "=========================================="
