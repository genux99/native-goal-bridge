# native-goal-bridge

Let a Hermes Agent start a native standing Goal in its current session, without a second execution loop.

**Experimental.** This plugin uses private Hermes GoalManager / SessionDB interfaces. It is not an official Nous plugin, and a catalog application is not an accepted listing. Tested against a local Hermes v0.22.5 installation on Windows; not certified against every later build or untested operating system.

## What it does

`goal_manage` exposes two actions:

- `create`: requires `objective`, `verification` and `stop_when`. Creates a native Goal only when this session has no existing goal record.
- `status`: reads the current Goal, including `turns_used` and `max_turns`.

The host injects the session ID. Model arguments cannot select a different session, force replacement, or set a budget. Existing records are never replaced, including paused, done and cleared goals. To set another goal after a terminal record, use the native `/goal` commands; the agent cannot reset it through this tool.

The plugin calls native `GoalManager.set()` through a local subclass with an insert-only persistence boundary. A concurrent existing record wins. It reads the state back before reporting success. The native engine owns judging, follow-up turns, budget exhaustion, pause and cancellation; the plugin creates no timer or worker.

## Installation

Install from the plugin repository:

```bash
hermes plugins install genux99/native-goal-bridge --no-enable --yes-deps
hermes plugins enable native-goal-bridge --no-allow-tool-override
```

For a reviewed immutable installation, add `--ref <full-40-character-commit-SHA>` to the install command. A tag or branch is not accepted by that flag.

An enable may report `deferred: tools (next session)`. Fixed tool schemas generally need a new session, while an existing Tool Search bridge may discover the tool immediately. Search, describe and call `goal_manage` with `{"action":"status"}` to check. Do not restart a running messaging gateway solely on the assumption that reload failed.

After catalog admission, installation by the bare name `native-goal-bridge` will become available. It is not promised before the catalog PR is merged.

## Example

```json
{
  "action": "create",
  "objective": "Produce a checked report for the user-authorized task.",
  "verification": "The report exists, tests ran successfully, and the final reply includes concrete evidence.",
  "stop_when": "Ask the user if a missing decision, new permission, blocker or scope change prevents completion."
}
```

Use it for bounded, multi-step work, not a simple question or indefinite monitoring. Native Goal judging can request another turn if the final response does not show the evidence, even when files already exist.

## Disclosure and trust boundaries

- Registers only `goal_manage` via `ctx.register_tool`, in the existing `messaging` toolset. No hooks, middleware, Desktop code, credential requirements or new runtime dependencies.
- Reads the current profile's Hermes configuration and reads/writes native goal records in that profile's `state.db`. It does not open a separate state database or store credentials.
- Imports `hermes_cli.goals` and `hermes_cli.config`; uses native private helpers including `_get_session_db` and `db._execute_write`. Validation may warn on these dependencies. They are intentionally disclosed, not bypassed or hidden with dynamic imports.
- Defines its own GoalManager subclass; does not rebind or monkey-patch a core class, module, function or dictionary in production.
- Makes no direct third-party network request, launches no shell process or background worker, and has no telemetry or self-updater. The **native Goal engine** may call the configured judge and schedule further model turns, consuming the existing model/turn budget.
- This is not a permission sandbox: approvals, stop conditions and user control still apply. No automatic approval, deletion, publishing, configuration change, budget reset or resumption is provided.
- Upgrade compatibility is not guaranteed for private interfaces; rerun validation and the tests after Hermes upgrades.

## Tests

Use a Hermes development/test Python environment with pytest, pytest-asyncio and Hermes's declared dependencies. Point `HERMES_AGENT_ROOT` at the Hermes checkout:

```bash
HERMES_AGENT_ROOT=/path/to/hermes-agent /path/to/test-python -m pytest tests -q
```

The suite uses real plugin discovery, dispatch, GoalManager and SQLite. Its model judge and platform transport are deterministic test doubles; no credentials or API spending are required. It covers existing-goal protection, malformed arguments, session/profile isolation, fixed budgets, pause/clear behavior, storage failures, thread/process contention and a native two-turn gateway continuation chain.

A separate local live Telegram trial also exercised real model tool calls and automatic native continuation. Private session records are intentionally not shipped in this repository.

## License

MIT. See LICENSE.

---

# 中文说明

让 Hermes Agent 自行启动**当前会话的原生 Goal**，不另造循环。

- 工具只有 `goal_manage create/status`。会话 ID 由宿主绑定，模型不能选别人的会话或指定预算。
- 已有记录（包括暂停、完成、取消）都不覆盖；原生预算不重置，暂停与取消仍用 `/goal`。
- 原生引擎负责判定与续跑；插件不创建定时器或后台工作进程。目标判定和后续模型调用仍会消耗既有模型额度。
- 读写当前 profile 的原生目标存储，依赖 `hermes_cli.goals`、`GoalManager`、`SessionDB` 等私有接口；验证器警告需公开披露，升级后要回归测试。
- 未绕过审批、未读取凭据、未植入遥测、未自更新，也不代表官方维护或已进入 catalog。
- 源码测试使用真实插件加载器和 SQLite，judge/平台传输使用确定性替身；另做过真实 Telegram 跨轮测试，但不公开私人会话记录。

安装与用法见前面的英文说明；启用后以工具真实可发现、可调用为准，不一概要求重启网关。
