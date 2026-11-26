import { api } from "../api/workbench.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { status } from "../components/common/status.js";
import { table } from "../components/common/table.js";
import { poll } from "../hooks/poll.js";
import { el } from "../utils/dom.js";
import { time } from "../utils/format.js";

const PENDING = new Set(["queued", "running"]);

function reportState(run) {
  const pending = PENDING.has(run.status);
  const hint = run.status === "queued"
    ? "批次已排队，等待 worker 领取，页面会自动更新。"
    : run.status === "running"
      ? `worker 正在处理（第 ${run.attempts} 次执行${run.attempts > 1 ? "，含超时接管" : ""}），页面会自动更新。`
      : run.failure || run.result?.summary;
  return el("div", {class: "stack", id: "run-state"}, status(run.status),
    el("p", {}, hint),
    run.status === "done" ? el("a", {class: "button", href: `#evidence/${run.id}`}, "查看业务证据") : null);
}

export async function runsPage(config, route, signal) {
  const items = await api.runs();
  const latest = route.id ? await api.run(route.id, signal) : items[0];
  const detail = latest ? reportState(latest) : empty("进入资料页，选用一个业务样本并提交执行。");
  async function refresh() {
    try {
      const next = await api.run(latest.id, signal);
      if (!signal.aborted) {
        detail.replaceChildren(...reportState(next).childNodes);
        const badge = document.querySelector(`[data-run="${next.id}"] .status`);
        if (badge) badge.replaceWith(status(next.status));
      }
      return PENDING.has(next.status);
    } catch (error) {
      if (!signal.aborted) detail.append(el("p", {role: "alert"}, error.message));
      return false;
    }
  }
  if (latest && PENDING.has(latest.status)) poll(refresh, signal);
  return el("div", {class: "page"},
    pageHeading(config.modules[2], config.parameter_label),
    latest ? section(latest.case_title, detail) : detail,
    section("执行批次", items.length ? table(["资料", "编号", "参数", "状态", "执行次数", "提交时间"],
      items.map(run => [el("a", {"data-run": run.id, href: `#runs/${run.id}`}, run.case_title), run.id,
        run.parameter, el("span", {"data-run": run.id}, status(run.status)), run.attempts,
        time(run.created_at)])), "执行批次") :
      empty("暂无执行记录。")));
}
