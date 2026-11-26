export const States = Object.freeze({
  queued: "等待执行", running: "执行中", done: "已完成", failed: "执行失败",
});

export const Actions = Object.freeze({
  create_case: "登记资料", enqueue: "提交执行", claim: "领取执行", reclaim: "超时接管",
  done: "执行完成", failed: "执行失败", review: "复核签署",
});
