# Pipelit 基础设施改进计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 7 个配置/行为问题：L1/L2 配置边界 bug、PIL 图片标注分析、分支创建逻辑、路径自动检测、主分支动态检测、多语言版本文件检测、SKILL.md 文档更新。

**Architecture:** 分三组：（A）Python 脚本 bug 修复与新功能；（B）新增 PIL 图片标注脚本并集成；（C）SKILL.md 文档对齐。每组可独立交付。

**Tech Stack:** Python 3.10+ stdlib、Pillow（可选，graceful fallback）、Markdown

## Global Constraints

- `feishu_api.py` 除 Pillow 相关部分外保持 stdlib-only
- `image_annotator.py` 允许 `import PIL`，不可用时输出 `{"error": "pillow_not_installed"}` 而非抛异常
- 所有 SKILL.md 修改不改变已有 Phase 编号，只改内容
- 不新增 CLI 命令以外的公开 API
- Windows 路径兼容（用 `pathlib.Path`，不拼 `/`）

---

## 文件变更清单

| 文件 | 操作 |
|------|------|
| `scripts/feishu_api.py` | 修改：修 `_save_release_mascot_config`、加 `detect_project_paths`、加 `detect_release_branch`、`get_task_full` 集成 annotator |
| `scripts/image_annotator.py` | 新建：PIL 标注检测 |
| `scripts/config_manager.py` | 修改：L1 overview 只展示 `user_id` |
| `skills/config/SKILL.md` | 修改：L1/L2 边界描述 |
| `skills/feishu-dev/SKILL.md` | 修改：1.2 图片处理、3.1 分支逻辑、首次配置向导 |
| `skills/release/SKILL.md` | 修改：Phase 0 向导简化、branch 动态检测、多语言版本文件 |

---

## Task 1：修复 `_save_release_mascot_config` L1→L2 Bug

**Files:**
- Modify: `scripts/feishu_api.py:1158-1168`

**Interfaces:**
- Produces: `_save_release_mascot_config(path, params)` 写 L2，不再污染 L1

- [ ] **Step 1: 理解当前 bug**

  当前代码（约第 1158 行）：
  ```python
  def _save_release_mascot_config(path: pathlib.Path, params: dict) -> None:
      cfg = load_merged_config()   # ← 读 L1+L2 合并结果
      release = cfg.get("release") or {}
      release["mascotImagePath"] = str(path)
      ...
      cfg["release"] = release
      _secure_write(CONFIG_FILE, ...)   # ← 写 L1！把 L2 的内容也升级到 L1
  ```

- [ ] **Step 2: 修复为读写 L2**

  将函数改为：
  ```python
  def _save_release_mascot_config(path: pathlib.Path, params: dict) -> None:
      cfg = _read_project_config()       # 只读 L2
      release = cfg.get("release") or {}
      release["mascotImagePath"] = str(path)
      if params.get("mascot_description"):
          release["mascotDescription"] = params["mascot_description"]
      if params.get("company_icon_path"):
          release["companyIconPath"] = params["company_icon_path"]
      cfg["release"] = release
      _write_project_config(cfg)         # 写 L2
  ```

- [ ] **Step 3: 手动验证**

  ```bash
  cd c:/Users/otsan.li/Desktop/work/skill/pipelit
  # 构造一个假参数文件
  echo '{"project_name":"test","save_to_config":false}' > /tmp/mascot-test.json
  # 确认 CONFIG_FILE（L1）在调用后不被修改
  python3 scripts/feishu_api.py check_config
  ```
  预期：不报错，L1 文件时间戳未变化

- [ ] **Step 4: Commit**

  ```bash
  git add scripts/feishu_api.py
  git commit -m "fix: _save_release_mascot_config write to L2 instead of L1"
  ```

---

## Task 2：`config_manager.py` 更新 L1 overview 只展示 user_id

**Files:**
- Modify: `scripts/config_manager.py:44-70`（`overview` 函数的 L1 部分）

**Interfaces:**
- Consumes: `feishu_api.read_config()` 返回 L1 内容
- Produces: overview JSON 中 `l1` 节点只包含 `user_id`

- [ ] **Step 1: 读懂当前 L1 overview 的内容**

  打开 `scripts/config_manager.py` 第 44 行附近，找到 `result["l1"]` 的赋值。当前它把 `app_id`、`app_secret` 也归进 L1 展示，这是误导。

- [ ] **Step 2: 修改 L1 节点只展示 user_id**

  找到 overview 函数中对 l1 的赋值，改为：
  ```python
  result["l1"] = {
      "file": str(feishu_api.CONFIG_FILE),
      "fields": {
          "user_id": _f(l1_cfg.get("user_id"), "ok" if l1_cfg.get("user_id") else "missing"),
      }
  }
  ```
  `app_id`/`app_secret` 等凭据从 L2 节点展示（`_read_project_config()` 已有）。

- [ ] **Step 3: 验证**

  ```bash
  cd c:/Users/otsan.li/Desktop/work/skill/pipelit
  python3 scripts/config_manager.py overview
  ```
  预期：L1 节点只有 `user_id`，L2 节点包含 `app_id`、`app_secret`（若已配置）

- [ ] **Step 4: Commit**

  ```bash
  git add scripts/config_manager.py
  git commit -m "fix: L1 overview shows only user_id"
  ```

---

## Task 3：新增 `detect_project_paths` CLI 命令

**Files:**
- Modify: `scripts/feishu_api.py`（新增函数 `detect_project_paths` + CLI 分发）

**Interfaces:**
- Produces: CLI `python3 feishu_api.py detect_project_paths`，返回：
  ```json
  {
    "frontend": {"path": "/abs/path", "type": "vue", "confidence": "high"},
    "backend": {"path": "/abs/path", "type": "python", "confidence": "medium"},
    "suggestions": ["..."]
  }
  ```

- [ ] **Step 1: 实现 `detect_project_paths` 函数**

  在 `feishu_api.py` 的 L2 Config Helpers 区域新增（约第 310 行后）：

  ```python
  def detect_project_paths(cwd: str | None = None) -> dict:
      """自动检测前后端项目路径，用于首次配置向导。"""
      base = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()

      FRONTEND_MARKERS = ["package.json", "vite.config.ts", "vue.config.js", "next.config.js"]
      BACKEND_MARKERS = ["pyproject.toml", "requirements.txt", "setup.py", "pom.xml", "build.gradle", "Cargo.toml"]

      def _detect_type(path: pathlib.Path) -> str | None:
          if (path / "package.json").exists():
              try:
                  pkg = json.loads((path / "package.json").read_text(encoding="utf-8"))
                  deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                  if "vue" in deps:
                      return "vue"
                  if "react" in deps or "next" in deps:
                      return "react"
              except Exception:
                  pass
              return "node"
          if (path / "pyproject.toml").exists() or (path / "requirements.txt").exists():
              return "python"
          if (path / "pom.xml").exists():
              return "java-maven"
          if (path / "build.gradle").exists():
              return "java-gradle"
          if (path / "Cargo.toml").exists():
              return "rust"
          return None

      result = {"frontend": None, "backend": None, "suggestions": []}

      # 1. 检测当前目录
      cur_type = _detect_type(base)
      if cur_type in ("vue", "react", "node"):
          result["frontend"] = {"path": str(base), "type": cur_type, "confidence": "high"}
      elif cur_type in ("python", "java-maven", "java-gradle", "rust"):
          result["backend"] = {"path": str(base), "type": cur_type, "confidence": "high"}

      # 2. 扫描兄弟目录（最多检查 10 个，避免超时）
      parent = base.parent
      siblings = [p for p in parent.iterdir() if p.is_dir() and p != base][:10]
      for sib in siblings:
          sib_type = _detect_type(sib)
          if not sib_type:
              continue
          if sib_type in ("vue", "react", "node") and not result["frontend"]:
              result["frontend"] = {"path": str(sib), "type": sib_type, "confidence": "medium"}
          elif sib_type in ("python", "java-maven", "java-gradle", "rust") and not result["backend"]:
              result["backend"] = {"path": str(sib), "type": sib_type, "confidence": "medium"}

      # 3. 生成用户可读的建议
      if result["frontend"]:
          conf = result["frontend"]["confidence"]
          result["suggestions"].append(
              f"前端: {result['frontend']['path']} ({result['frontend']['type']}, {conf})"
          )
      if result["backend"]:
          conf = result["backend"]["confidence"]
          result["suggestions"].append(
              f"后端: {result['backend']['path']} ({result['backend']['type']}, {conf})"
          )
      if not result["frontend"] and not result["backend"]:
          result["suggestions"].append("未检测到已知项目类型，请手动填写路径")

      return result
  ```

- [ ] **Step 2: 在 CLI main() 中注册命令**

  在 `main()` 的 `elif` 链中加入（放在 `save_project_config` 附近）：
  ```python
  elif cmd == "detect_project_paths":
      cwd = args[1] if len(args) > 1 else None
      out = detect_project_paths(cwd)
  ```

- [ ] **Step 3: 验证**

  ```bash
  cd c:/Users/otsan.li/Desktop/work/skill/pipelit
  python3 scripts/feishu_api.py detect_project_paths
  ```
  预期：返回 JSON，至少有 `suggestions` 字段不为空

- [ ] **Step 4: Commit**

  ```bash
  git add scripts/feishu_api.py
  git commit -m "feat: add detect_project_paths CLI command"
  ```

---

## Task 4：新增 `detect_release_branch` CLI 命令

**Files:**
- Modify: `scripts/feishu_api.py`（新增 `detect_release_branch` 函数 + CLI 注册）

**Interfaces:**
- Produces: CLI `python3 feishu_api.py detect_release_branch [repo_path]`，返回：
  ```json
  {
    "branch": "main",
    "version_file": "package.json",
    "version_updater": "npm",
    "detection_method": "symbolic-ref"
  }
  ```

- [ ] **Step 1: 实现 `detect_release_branch` 函数**

  ```python
  def detect_release_branch(repo_path: str | None = None) -> dict:
      """检测仓库主分支名称和版本文件类型。"""
      import subprocess
      path = pathlib.Path(repo_path) if repo_path else pathlib.Path.cwd()

      result = {
          "branch": "main",
          "version_file": None,
          "version_updater": None,
          "detection_method": "default",
      }

      # 检测主分支
      try:
          r = subprocess.run(
              ["git", "-C", str(path), "symbolic-ref", "refs/remotes/origin/HEAD"],
              capture_output=True, text=True, timeout=5
          )
          if r.returncode == 0:
              ref = r.stdout.strip()  # refs/remotes/origin/main
              result["branch"] = ref.split("/")[-1]
              result["detection_method"] = "symbolic-ref"
      except Exception:
          pass

      if result["detection_method"] == "default":
          # fallback：检查 main/master 哪个存在
          try:
              r = subprocess.run(
                  ["git", "-C", str(path), "branch", "-r"],
                  capture_output=True, text=True, timeout=5
              )
              branches = r.stdout
              if "origin/main" in branches:
                  result["branch"] = "main"
                  result["detection_method"] = "branch-list"
              elif "origin/master" in branches:
                  result["branch"] = "master"
                  result["detection_method"] = "branch-list"
          except Exception:
              pass

      # 检测版本文件
      version_file_map = [
          ("package.json", "npm"),
          ("pyproject.toml", "poetry"),
          ("setup.py", "setuptools"),
          ("pom.xml", "maven"),
          ("build.gradle", "gradle"),
          ("Cargo.toml", "cargo"),
      ]
      for fname, updater in version_file_map:
          if (path / fname).exists():
              result["version_file"] = fname
              result["version_updater"] = updater
              break

      return result
  ```

- [ ] **Step 2: 在 CLI main() 中注册**

  ```python
  elif cmd == "detect_release_branch":
      repo_path = args[1] if len(args) > 1 else None
      out = detect_release_branch(repo_path)
  ```

- [ ] **Step 3: 验证**

  ```bash
  cd c:/Users/otsan.li/Desktop/work/skill/pipelit
  python3 scripts/feishu_api.py detect_release_branch
  ```
  预期：返回 `branch`（main 或 master）、`version_file`（若目录有对应文件）

- [ ] **Step 4: Commit**

  ```bash
  git add scripts/feishu_api.py
  git commit -m "feat: add detect_release_branch CLI command"
  ```

---

## Task 5：新建 `scripts/image_annotator.py`

**Files:**
- Create: `scripts/image_annotator.py`

**Interfaces:**
- Produces: CLI `python3 image_annotator.py analyze <image_path>`，返回：
  ```json
  {
    "annotations": [
      {"color": "red", "bbox": [x1, y1, x2, y2], "crop_path": "/tmp/pipelit_ann_0.png"}
    ],
    "annotation_count": 1
  }
  ```
  若 Pillow 未安装：`{"error": "pillow_not_installed", "install": "pip install Pillow"}`

- [ ] **Step 1: 写 `image_annotator.py`**

  ```python
  #!/usr/bin/env python3
  """
  Pipelit 图片标注检测器 — 检测图片中的红/绿色圈注区域。
  需要 Pillow：pip install Pillow

  Usage:
    python3 image_annotator.py analyze <image_path>

  Output: JSON to stdout
  """
  import sys
  import json
  import pathlib
  import tempfile

  try:
      sys.stdout.reconfigure(encoding="utf-8")
      sys.stderr.reconfigure(encoding="utf-8")
  except AttributeError:
      pass


  def _check_pillow():
      try:
          from PIL import Image  # noqa: F401
          return True
      except ImportError:
          return False


  def analyze_annotations(image_path: str) -> dict:
      """检测图片中的彩色圈注区域（红/绿/黄），输出标注列表。"""
      if not _check_pillow():
          return {"error": "pillow_not_installed", "install": "pip install Pillow"}

      from PIL import Image
      import colorsys

      path = pathlib.Path(image_path)
      if not path.exists():
          return {"error": f"文件不存在: {image_path}"}

      img = Image.open(path).convert("RGB")
      width, height = img.size
      pixels = img.load()

      # HSV 阈值：高饱和度 + 目标色相范围
      TARGET_COLORS = {
          "red":   [(0, 10), (350, 360)],   # 色相范围（度），S>0.5, V>0.3
          "green": [(100, 140)],
          "yellow": [(40, 65)],
      }

      def _classify_pixel(r, g, b):
          h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
          if s < 0.45 or v < 0.3:
              return None
          hue = h * 360
          for color, ranges in TARGET_COLORS.items():
              for lo, hi in ranges:
                  if lo <= hue <= hi:
                      return color
          return None

      # 降采样扫描（每 4 px 取一次，提升速度）
      STEP = 4
      color_pixels: dict[str, list[tuple[int, int]]] = {}
      for y in range(0, height, STEP):
          for x in range(0, width, STEP):
              c = _classify_pixel(*pixels[x, y])
              if c:
                  color_pixels.setdefault(c, []).append((x, y))

      # 找连通区域（简单 bbox 聚合）
      annotations = []
      for color, pts in color_pixels.items():
          if len(pts) < 10:   # 太少的像素不算标注
              continue
          xs = [p[0] for p in pts]
          ys = [p[1] for p in pts]
          x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
          # 扩展 20px margin
          x1 = max(0, x1 - 20)
          y1 = max(0, y1 - 20)
          x2 = min(width, x2 + 20)
          y2 = min(height, y2 + 20)

          # 裁剪并保存
          crop = img.crop((x1, y1, x2, y2))
          tmp = tempfile.NamedTemporaryFile(
              prefix="pipelit_ann_", suffix=".png", delete=False
          )
          crop.save(tmp.name)

          annotations.append({
              "color": color,
              "bbox": [x1, y1, x2, y2],
              "crop_path": tmp.name,
              "pixel_count": len(pts),
          })

      # 按像素数降序排列（最显眼的标注在前）
      annotations.sort(key=lambda a: a["pixel_count"], reverse=True)

      return {"annotations": annotations, "annotation_count": len(annotations)}


  def main():
      args = sys.argv[1:]
      if not args or args[0] == "analyze" and len(args) < 2:
          print(__doc__)
          sys.exit(0)
      cmd = args[0]
      if cmd == "analyze":
          out = analyze_annotations(args[1])
      else:
          out = {"error": f"未知命令: {cmd}"}
      print(json.dumps(out, ensure_ascii=False, indent=2))


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 2: 验证（无 Pillow 时 graceful）**

  ```bash
  python3 scripts/image_annotator.py analyze /nonexistent.png
  ```
  若 Pillow 未安装：预期输出 `{"error": "pillow_not_installed", ...}`
  若 Pillow 已安装：预期输出 `{"error": "文件不存在: /nonexistent.png"}`

- [ ] **Step 3: Commit**

  ```bash
  git add scripts/image_annotator.py
  git commit -m "feat: add PIL-based image annotation detector"
  ```

---

## Task 6：`get_task_full` 集成 image_annotator

**Files:**
- Modify: `scripts/feishu_api.py:803-843`（`get_task_full` 函数的图片处理部分）

**Interfaces:**
- Consumes: `image_annotator.py analyze <path>` 的 JSON 输出
- Produces: `get_task_full` 返回值新增 `image_annotations` 字段（每张图片的标注结果）

- [ ] **Step 1: 在 `get_task_full` 的图片处理区域加入 annotator 调用**

  找到第 804 行 `attachments = fetch_task_images(tid, token)` 之后，在 `result` dict 构建前（约 817 行）插入：

  ```python
  # 图片标注分析（若 image_annotator 可用）
  image_annotations = {}
  if images:
      import subprocess as _sp
      annotator = pathlib.Path(__file__).parent / "image_annotator.py"
      for img in images:
          img_path = img.get("path")
          if not img_path:
              continue
          try:
              r = _sp.run(
                  [sys.executable, str(annotator), "analyze", img_path],
                  capture_output=True, text=True, timeout=15
              )
              if r.returncode == 0:
                  ann = json.loads(r.stdout)
                  if not ann.get("error"):
                      image_annotations[img_path] = ann
          except Exception:
              pass  # annotator 失败不阻断主流程
  ```

  然后在 `result` dict 中加入：
  ```python
  "image_annotations": image_annotations,
  ```

- [ ] **Step 2: 验证**

  ```bash
  python3 scripts/feishu_api.py get_task_full <任意有效task_id>
  ```
  预期：返回 JSON 中有 `image_annotations` 字段（即使为 `{}`）

- [ ] **Step 3: Commit**

  ```bash
  git add scripts/feishu_api.py
  git commit -m "feat: integrate image_annotator into get_task_full"
  ```

---

## Task 7：更新 `feishu-dev/SKILL.md`

**Files:**
- Modify: `skills/feishu-dev/SKILL.md`（三处：1.2 图片处理、3.1 分支逻辑、首次配置向导）

**Interfaces:**
- Consumes: `get_task_full` 返回的 `image_annotations` 字段（Task 6 产出）
- Consumes: `detect_project_paths` CLI（Task 3 产出）

### 7a. 更新 1.2 图片处理节

- [ ] **Step 1: 替换 1.2 中的图片分析描述**

  找到 `### 1.2 附件图片处理` 节，将"读图时重点关注"到"记录为 `red_annotations`"这段替换为：

  ```markdown
  读图时，同时使用结构化标注数据辅助分析：

  **`image_annotations` 字段**（由 image_annotator 自动产出）：
  若 `image_annotations[<path>].annotation_count > 0`，优先读取标注列表：
  - `color`：标注颜色（`red` / `green` / `yellow`），红色为最高优先级
  - `crop_path`：已裁剪的标注区域图片路径，用 Read 工具读取放大查看
  - 标注区域旁边的文字是用户的说明，是定位 bug 的首要线索

  若 `image_annotations` 为空（Pillow 未安装或标注颜色太淡）：降级到直接用 Read 读原图，人工识别红色圈/框/箭头。

  记录所有标注信息为 `red_annotations`，在后续分析中优先作为定位依据。
  ```

### 7b. 更新 3.1 分支创建逻辑

- [ ] **Step 2: 替换 3.1 执行规则**

  找到 `**执行规则**：` 下的条目列表，替换为三段式逻辑：

  ```markdown
  **执行规则（三段式）**：

  1. `cd` 到该仓库路径，获取当前分支名
  2. 判断：
     - 当前分支为 `master`/`main`/`dev` → 创建 `feat/feishu-{task_id 前 8 位}`
     - 当前分支为 `feat/feishu-{本任务 id 前 8 位}` → 直接使用，输出 `[3.1-<repo>] 复用已有分支: <branch>`
     - 当前分支为其他 `feat/xxx` → 通过 AskUserQuestion 询问用户：
       ```
       当前在分支 <branch>，不是主干分支。
       如何处理？
         ● 在当前分支继续开发（适合同一功能的延续）
         ○ 新建独立分支 feat/feishu-{task_id 前 8 位}
       ```
       用户选"继续"→ 使用当前分支；选"新建"→ 创建新分支
  3. **强制输出 log**，每个仓库一行（同原格式）
  ```

### 7c. 更新首次配置向导（1.1）

- [ ] **Step 3: 替换首次配置向导中路径收集逻辑**

  找到 `#### 首次配置向导` 下 `**禁止从 memory 自动填充任何路径或凭据。**` 这段，在 AskUserQuestion 之前加入自动检测步骤：

  ```markdown
  首次配置前，**先自动检测项目路径**：

  ```bash
  PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" detect_project_paths
  ```

  若检测到路径（`frontend` 或 `backend` 字段不为 null），通过 AskUserQuestion 展示检测结果并让用户确认：

  ```
  检测到可能的项目路径：
    前端: <frontend.path>（<frontend.type>，置信度：<frontend.confidence>）
    后端: <backend.path>（<backend.type>，置信度：<backend.confidence>）

  是否使用以上路径？
    ● 确认（直接使用）
    ○ 手动调整
  ```

  用户选"确认"→ 直接调用 `save_project_config`；选"调整"→ 走原有的手动填写流程。

  检测结果为空时，跳过检测步骤，直接走手动填写流程。
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add skills/feishu-dev/SKILL.md
  git commit -m "docs: update feishu-dev skill - PIL annotations, branch logic, path detection"
  ```

---

## Task 8：更新 `release/SKILL.md`

**Files:**
- Modify: `skills/release/SKILL.md`（Phase 0：向导简化、动态 branch/version file 检测）

**Interfaces:**
- Consumes: `detect_release_branch` CLI（Task 4 产出）

### 8a. Phase 0 添加自动检测步骤

- [ ] **Step 1: 在 Phase 0 `configured: false` 向导前加入自动检测**

  找到 `### 若 \`configured: false\`` 段，在"通过 AskUserQuestion 询问以下问题"之前插入：

  ```markdown
  **首先自动检测仓库信息：**

  ```bash
  PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" detect_release_branch
  ```

  记录返回的 `branch`、`version_file`、`version_updater` 作为向导的默认值。
  ```

### 8b. 简化向导：问题 1 合并检测结果

- [ ] **Step 2: 修改问题 1（仓库数量）补充检测到的分支**

  **问题 1** 改为：
  ```markdown
  **问题 1：仓库数量与主分支**
  ```
  检测到主分支为 `<detected_branch>`（置信度：`<detection_method>`）。
  ```
  这个项目有几个仓库需要发版？
    ● 1 个（当前目录，主分支：<detected_branch>）
    ○ 2 个（前端 + 后端，分别填路径）
  ```
  若检测失败（detection_method = "default"），在选项旁补充括号提示用户确认。
  ```

### 8c. 简化向导：问题 2 展示检测到的版本文件

- [ ] **Step 3: 修改问题 2（版本号文件）展示检测结果**

  **问题 2** 改为：
  ```markdown
  **问题 2：版本号文件**
  ```
  检测到版本文件：`<detected_version_file>`（<detected_version_updater>）
  ```
  确认或选择版本号存储位置：
    ● <detected_version_file>（检测到，推荐）
    ○ package.json（Node.js 前端）
    ○ pyproject.toml（Python）
    ○ 其他（手动填写）
  ```
  若未检测到则展示原始选项列表，第一项不带"推荐"标记。
  ```

### 8d. 可选配置延后（问题 3-6 标记为可选，不阻断）

- [ ] **Step 4: 修改问题 3-6 的阻断逻辑**

  在问题 3（Changelog）之前加注：

  ```markdown
  > 以下问题均为可选配置，选"跳过"不影响发版。发版完成后可随时通过 `/pipelit:config` 补充。
  ```

  每个问题的选项加入"暂时跳过"作为选项之一（非默认）。

- [ ] **Step 5: Commit**

  ```bash
  git add skills/release/SKILL.md
  git commit -m "docs: release skill Phase 0 - auto-detect branch/version file, simplify wizard"
  ```

---

## Task 9：更新 `config/SKILL.md` L1/L2 描述

**Files:**
- Modify: `skills/config/SKILL.md`

- [ ] **Step 1: 修改 L1/L2 展示格式描述**

  找到 config SKILL.md 中的展示格式，修改 L1 节点描述：

  ```markdown
  📁 L1  ~/.claude/pipelit/config.json
    user_id        <值>                  <状态>
    （仅存储跨项目的用户身份，凭据保存在 L2）
  ```

  L2 节点新增 `app_id` / `app_secret` 在"飞书"子节下：

  ```markdown
  📁 L2  .claude/pipelit/config.json
    飞书
      app_id       <值>                  <状态>
      app_secret   ••••••                <状态>
      token        <有效至/已过期>        <状态>
    项目路径
      ...（同原格式）
  ```

- [ ] **Step 2: 修改"修改字段"部分的说明**

  在支持的字段列表中把 `app_id` / `app_secret` 的注释改为"存储在 L2 项目级"，把 `user_id` 注释改为"存储在 L1 用户级"。

- [ ] **Step 3: Commit**

  ```bash
  git add skills/config/SKILL.md
  git commit -m "docs: update config skill L1/L2 boundary documentation"
  ```

---

## 验证完整性自查

- Task 1 修复了 `_save_release_mascot_config` 写 L1 的 bug ✓
- Task 2 config_manager 只展示 `user_id` 在 L1 ✓
- Task 3 新增 `detect_project_paths` 供 SKILL 调用 ✓
- Task 4 新增 `detect_release_branch` 供 release SKILL 调用 ✓
- Task 5 PIL annotator 新建，Pillow 不可用时 graceful ✓
- Task 6 `get_task_full` 集成 annotator，失败不阻断 ✓
- Task 7 feishu-dev SKILL 三处更新（图片、分支、向导）✓
- Task 8 release SKILL Phase 0 向导简化 ✓
- Task 9 config SKILL L1/L2 描述对齐 ✓

未覆盖的讨论点：

- **Point 7（为什么 skill 有时不按预期执行）**：这是元问题，不适合写成代码任务，应通过后续迭代中在每个 SKILL 里补充强制 log 和 `[MUST]` 标注来逐步改善，而非单次修改。
