// 问卷系统 —— 公共 JS 工具
async function api(url, method = "GET", body = null) {
  const opt = { method, headers: {} };
  if (body) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const res = await fetch(url, opt);
  let data = null;
  try { data = await res.json(); } catch (e) { /* 非 JSON */ }
  if (res.status === 401) {
    location.href = "/";
    throw new Error("未登录");
  }
  if (!res.ok || !data || data.ok !== true) {
    throw new Error((data && data.error) || ("请求失败 " + res.status));
  }
  return data;
}

function qs(name) {
  return new URLSearchParams(location.search).get(name);
}

function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function fmtDate(s) {
  if (!s) return "-";
  const d = new Date(s);
  if (isNaN(d)) return s;
  return d.toLocaleString("zh-CN", { hour12: false });
}
