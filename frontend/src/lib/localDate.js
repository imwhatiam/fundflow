/**
 * 使用浏览器本地日历日期生成 ISO 日期字符串，避免 toISOString() 在非 UTC 时区跨日。
 */
export function formatLocalDate(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
