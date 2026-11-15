"""One-click diagnostics for the bot, integrations, and privacy guarantees."""

from __future__ import annotations

import ctypes
import importlib.util
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .model_client import make_client
from .paths import DATA, LOGS, STICKER_DIR
from .wechat_adapter import detect_wechat_backends

log = logging.getLogger(__name__)

Progress = Optional[Callable[[int, str], None]]


def _check(title: str, status: str, detail: str, hint: str = "") -> dict:
    return {"title": title, "status": status, "detail": detail, "hint": hint}


def _writable(folder: Path) -> tuple[bool, str]:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write-test-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, str(folder)
    except OSError as exc:
        return False, str(exc)


def run_diagnostics(service, run_model: bool = True, run_chat_test: bool = False,
                    progress: Progress = None) -> dict:
    checks: list[dict] = []
    total = 14 if run_chat_test else 13

    def step(index: int, name: str) -> None:
        if progress:
            try:
                progress(int(index / total * 100), name)
            except Exception:
                pass

    # 1. Runtime ---------------------------------------------------------
    step(1, "检查运行环境")
    py_ok = sys.version_info >= (3, 9)
    bits = platform.architecture()[0]
    checks.append(_check(
        "Python 运行环境",
        "ok" if py_ok and bits == "64bit" else ("warn" if py_ok else "fail"),
        f"Python {platform.python_version()} · {bits} · {platform.system()}",
        "" if py_ok and bits == "64bit" else "建议使用 64 位 Python 3.10–3.12",
    ))

    # 2. Filesystem ------------------------------------------------------
    step(2, "检查数据目录")
    write_results = {name: _writable(folder) for name, folder in
                     (("data", DATA), ("logs", LOGS), ("stickers", STICKER_DIR))}
    failed = [name for name, (ok, _) in write_results.items() if not ok]
    checks.append(_check(
        "数据目录写入",
        "ok" if not failed else "fail",
        "data / logs / stickers 均可写入" if not failed else f"不可写：{', '.join(failed)}",
        "请检查文件夹权限，或以普通用户身份重新解压程序" if failed else "",
    ))

    # 3. Configuration ---------------------------------------------------
    step(3, "校验配置")
    cfg = service.config.data
    try:
        cfg = service.config.reload()
        context_limit = int(cfg["bot"]["context_limit"])
        profile = service.config.active_profile()
        if context_limit < 20:
            raise ValueError("上下文条数小于 20")
        ok = bool(profile) and bool(cfg.get("active_persona_id"))
        checks.append(_check(
            "配置与上下文设置",
            "ok" if ok else "warn",
            f"上下文 {context_limit} 条 · 当前模型 {profile.get('model', '未选')}",
            "" if ok else "请在设置中至少保留 20 条上下文",
        ))
    except Exception as exc:
        checks.append(_check("配置与上下文设置", "fail", f"配置读取失败：{exc}",
                             "打开设置重新保存，或备份后删除 data/config.json"))

    # 4. Database --------------------------------------------------------
    step(4, "检查本地记忆库")
    db_ok, db_detail = service.memory.integrity()
    stats = service.memory.stats()
    checks.append(_check(
        "本地上下文数据库",
        "ok" if db_ok else "fail",
        f"SQLite {db_detail} · 已保存 {stats['total']} 条消息",
        "" if db_ok else "关闭程序后备份并删除 data/arona.db，再重新启动",
    ))

    try:
        train_stats = service.training.stats()
        train_enabled = bool(cfg.get("training", {}).get("enabled", True))
        if not train_stats["docs"]:
            checks.append(_check("本地训练知识库", "warn", "尚未上传训练资料",
                                 "打开「本地训练」上传 txt/md/docx/pdf 等资料"))
        elif not train_enabled:
            checks.append(_check("本地训练知识库", "warn",
                                 f"{train_stats['docs']} 个文件 · 训练开关已关闭",
                                 "到「本地训练」启用本地知识训练"))
        else:
            checks.append(_check(
                "本地训练知识库", "ok",
                f"{train_stats['docs']} 个文件 · {train_stats['chunks']} 个片段 · 已启用",
            ))
    except Exception as exc:
        checks.append(_check("本地训练知识库", "warn", f"读取失败：{exc}",
                             "到「本地训练」重建索引，或删除 data/training.db 后重试"))

    # 5. Personas --------------------------------------------------------
    step(5, "检查人格设定")
    persona = service.personas.get(cfg.get("active_persona_id"))
    has_core = bool(persona.get("name")) and bool(persona.get("system_prompt") or persona.get("description"))
    checks.append(_check(
        "人格与语气配置",
        "ok" if has_core else "warn",
        f"当前人格：{persona.get('name', '未设置')} · {persona.get('title', '')}",
        "" if has_core else "请补充人格的核心设定或角色描述",
    ))

    # 6. Stickers --------------------------------------------------------
    step(6, "检查表情包")
    stickers = service.stickers.enabled()
    all_stickers = service.stickers.list()
    missing = [s for s in all_stickers if not service.stickers.path_for(s).is_file()]
    if stickers:
        status = "warn" if missing else "ok"
        detail = f"{len(stickers)} 张可用表情包"
        if missing:
            detail += f" · {len(missing)} 个文件缺失"
        checks.append(_check("表情包资源", status, detail,
                             "删除缺失文件的表情包条目或重新导入" if missing else ""))
    else:
        checks.append(_check("表情包资源", "warn", "没有启用的表情包",
                             "在表情包页导入 PNG/GIF，或重新扫描示例表情包"))

    # 7. Privacy ---------------------------------------------------------
    step(7, "验证隐私模式")
    privacy = service.config.data.get('privacy', {})
    privacy_ok = (not privacy.get('wechat_read_screenshots', False)
                  and not privacy.get('wechat_read_screen_recording', False))
    checks.append(_check(
        "隐私与依赖边界",
        "ok" if privacy_ok else "warn",
        "微信内部函数监听和发送 · 无需微信置于前台"
        if privacy_ok else "微信读取的截图或录屏保护未启用",
        "" if privacy_ok else "请检查微信读取隐私设置",
    ))

    # 8. Model config ----------------------------------------------------
    step(8, "检查模型配置")
    profile = service.config.active_profile()
    provider = str(profile.get("provider", ""))
    configured = provider == "mock" or (bool(profile.get("model")) and
                                        (provider == "ollama" or bool(profile.get("base_url"))))
    checks.append(_check(
        "模型配置",
        "ok" if configured else "fail",
        f"{profile.get('name', '未命名')} · {provider} · {profile.get('model', '未选模型')}",
        "" if configured else "在「模型与 API」页填写地址和模型名",
    ))

    # 9. Model connectivity ---------------------------------------------
    step(9, "连接模型服务")
    if not run_model:
        checks.append(_check("模型连接", "warn", "已跳过在线检测", "点击“检测模型”单独测试"))
    else:
        started = time.perf_counter()
        try:
            health = make_client(profile).health()
            checks.append(_check(
                "模型连接",
                "ok" if health.ok else "fail",
                (health.message + (f" · {health.detail}" if health.detail else ""))[:300],
                "" if health.ok else
                ("启动 Ollama：ollama serve；并确认模型已 pull" if provider == "ollama"
                 else "检查 API 地址、Key、余额与网络代理"),
            ))
        except Exception as exc:
            checks.append(_check("模型连接", "fail", f"检测异常：{exc}", "检查模型配置"))

    step(10, '检查原生微信依赖')
    backends=detect_wechat_backends()
    checks.append(_check('原生微信通道','ok' if backends.get('native') else 'fail',
                         'Wemac-auto + Frida 内部函数后端' if backends.get('native') else '原生依赖尚未安装'))
    step(11, '核对原生 profile')
    from .paths import DEFAULT_NATIVE_PROFILE
    import json
    path=Path(cfg.get('wechat',{}).get('native_profile') or DEFAULT_NATIVE_PROFILE).expanduser()
    try:
        native=json.loads(path.read_text())
        app_path=Path(native['app'])
        checks.append(_check('原生 profile','ok' if app_path.exists() else 'fail',
                             f'{path.name} · {app_path.name}', '启动时会严格核对版本、签名及函数指令。'))
    except Exception as exc:
        checks.append(_check('原生 profile','fail',str(exc),'在设置中指定本机独立微信 profile。'))

    # 12. Live connection ----------------------------------------------
    step(12, "检查实时监听")
    if service.running and service.adapter:
        ok, message = service.adapter.probe()
        checks.append(_check(
            "实时监听状态",
            "ok" if ok else "warn",
            message + f" · {service.adapter.backend_label} · 监听 "
            f"{len(service.config.enabled_targets())} 个对象",
            "" if ok else "点击「重启机器人」重新建立原生连接",
        ))
    else:
        checks.append(_check("实时监听状态", "warn", "机器人当前未启动",
                             "在控制台点击「启动机器人」后再次检测"))

    # 13. Target whitelist ---------------------------------------------
    step(13, "检查监听白名单")
    targets = service.config.enabled_targets()
    checks.append(_check(
        "测试对象白名单",
        "ok" if targets else "warn",
        f"{len(targets)} 个启用对象：" + "、".join(t["name"] for t in targets[:5])
        if targets else "尚未添加任何测试对象",
        "" if targets else "在「测试对象」页添加好友或群聊名称；未加入白名单的会话不会收到回复",
    ))

    # 14. End-to-end conversation test ---------------------------------
    if run_chat_test:
        step(14, "运行上下文对话测试")
        test_chat = "自动调试::上下文测试"
        try:
            service.memory.clear(test_chat)
            first = service.debug_chat("你好，请用一句话向老师打招呼。", chat_name=test_chat)
            service.debug_chat("记住一个口令：蓝色档案。", chat_name=test_chat)
            third = service.debug_chat("老师刚才让你记住的口令是什么？只回答口令。",
                                       chat_name=test_chat)
            remembered = "蓝色" in third.get("text", "") or "档案" in third.get("text", "")
            got_sticker = bool(first.get("sticker") or third.get("sticker"))
            if remembered:
                status = "ok"
                detail = "三轮上下文测试通过，模型记住了前文口令"
            else:
                status = "warn"
                detail = "对话链路已通，但模型未稳定复述前文口令：" + third.get("text", "")[:80]
            if not got_sticker:
                detail += " · 本轮未触发表情包（可接受）"
            checks.append(_check("自动对话与上下文", status, detail,
                                 "" if remembered else "上下文窗口较小或模型指令跟随较弱，可尝试更大的上下文设置"))
        except Exception as exc:
            checks.append(_check("自动对话与上下文", "fail", f"对话测试失败：{exc}",
                                 "检查模型服务与 API 配置；详细错误见运行日志"))
        finally:
            try:
                service.memory.clear(test_chat)
            except Exception:
                pass

    passed = sum(1 for c in checks if c["status"] == "ok")
    warnings = sum(1 for c in checks if c["status"] == "warn")
    failed = sum(1 for c in checks if c["status"] == "fail")
    overall = "fail" if failed else ("warn" if warnings else "ok")
    result = {
        "overall": overall,
        "passed": passed,
        "warnings": warnings,
        "failed": failed,
        "total": len(checks),
        "checks": checks,
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": __version__,
    }
    log.info("自动调试完成：%d 通过 / %d 警告 / %d 失败", passed, warnings, failed)
    if progress:
        try:
            progress(100, "调试完成")
        except Exception:
            pass
    return result
