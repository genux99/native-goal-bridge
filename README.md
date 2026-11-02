# native-goal-bridge

Let a Hermes Agent start a native standing Goal in its current session, without a second execution loop.

**Experimental.** This plugin uses private Hermes GoalManager / SessionDB interfaces. It is not an official Nous plugin, and a catalog application is not an accepted listing. Tested against a local Hermes v0.22.5 installation on Windows; not certified against every later build or untested operating system.

## What it does

`goal_manage` exposes five actions:

- `create`: requires `objective`, `verification` and `stop_when`. Creates a native Goal only when this session has no existing goal record.
- `status`: reads the current Goal, including `turns_used` and `max_turns`.
- `update`: supplies at least one of `objective`, `verification`, `stop_when`; edits an active or paused goal while retaining identity, status, budget, unedited contract fields and other criteria. It does not resume a paused goal.
- `pause`: stops future Goal continuation, not an already-running tool. Repeating it on a paused goal is a no-op.
- `resume`: continues an active/paused goal without resetting used or maximum turns. Exhausted budgets and terminal records are rejected; an already active goal is a no-op (use native `/goal unwait` for a parked wait barrier).

The host injects the session ID. Model arguments cannot select another session, force replacement or set a budget. Creation never replaces an existing record. Controls do not revive done/cleared goals; use native user commands for a new goal after a terminal record. Cancellation stays `/goal clear`.

Creation uses native `GoalManager.set()` with a plugin-local insert-only persistence hook. Controls reuse native pause/resume/contract methods through a plugin-local compare-and-swap write: a newer row causes `goal_changed`, not an overwrite. This guards this plugin's commit, not later writes by a stale native manager. Successful writes are read back before reporting success. The native engine still owns judging and follow-up scheduling; the plugin creates no timer or worker.

Only update or resume a user-controlled goal when the user requests it; never automatically undo a user pause. These are agent judgment rules, not a separate authorization sandbox in the handler.

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
- This is not a permission sandbox: approvals, stop conditions and user control still apply. No automatic approval, deletion, publishing, configuration change or budget reset is provided; resumption requires an explicit `resume` tool call and must follow the user's instruction.
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

- 工具支持 `create / status / update / pause / resume`。会话由宿主绑定，不接受任意会话、预算或重置参数。
- 创建不覆盖已有记录；修改保留目标身份、暂停状态和预算；继续不清零已用轮数，额度耗尽则拒绝。完成/取消记录不能复活。
- 暂停阻止后续自动续跑，不强杀在执行的工具；修改或继续用户目标须按用户指示，取消仍走 `/goal clear`。
- 原生引擎负责判定与续跑；插件不创建定时器或后台工作进程。目标判定和后续模型调用仍会消耗既有模型额度。
- 读写当前 profile 的原生目标存储，依赖 `hermes_cli.goals`、`GoalManager`、`SessionDB` 等私有接口；验证器警告需公开披露，升级后要回归测试。
- 未绕过审批、未读取凭据、未植入遥测、未自更新，也不代表官方维护或已进入 catalog。
- 源码测试使用真实插件加载器和 SQLite，judge/平台传输使用确定性替身；另做过真实 Telegram 跨轮测试，但不公开私人会话记录。

安装与用法见前面的英文说明；启用后以工具真实可发现、可调用为准，不一概要求重启网关。
