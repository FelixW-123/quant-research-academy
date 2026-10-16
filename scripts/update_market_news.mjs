import {writeFileSync} from "node:fs";

const searches = [
  ["市场", "US stocks market Wall Street breaking when:1d"],
  ["财报", "earnings results guidance revenue profit stocks when:1d"],
  ["宏观", "Federal Reserve Powell FOMC interest rates inflation when:1d"],
  ["宏观", "US CPI PPI jobs payroll GDP retail sales Treasury yields when:1d"],
  ["公司", "company launches announces product AI chip drug approval stocks when:1d"],
  ["政策", "merger acquisition antitrust SEC lawsuit tariff sanctions stocks when:1d"],
  ["行业", "semiconductor banks energy oil OPEC gold crypto stocks when:1d"],
  ["市场", "site:reuters.com US stocks earnings Fed when:1d"],
  ["市场", "site:cnbc.com stock market earnings Fed when:1d"]
];
const official = [["宏观", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml"]];
const editorial = [["市场", "MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"]];

function decode(value) {
  return value.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi, (_, entity) => {
      if (entity[0] === "#") {
        const n = entity[1]?.toLowerCase() === "x" ? parseInt(entity.slice(2), 16) : parseInt(entity.slice(1), 10);
        return Number.isFinite(n) && n <= 0x10ffff ? String.fromCodePoint(n) : "";
      }
      return {amp:"&",lt:"<",gt:">",quot:'"',apos:"'",nbsp:" "}[entity.toLowerCase()] || "";
    }).replace(/<[^>]+>/g, "").trim();
}
function field(xml, tag) {
  const found = xml.match(new RegExp("<" + tag + "(?:\\s[^>]*)?>([\\s\\S]*?)<\\/" + tag + ">", "i"));
  return found ? decode(found[1]) : "";
}
function classify(title, fallback) {
  const t = title.toLowerCase();
  if (/federal reserve|\bfed\b|fomc|powell|interest rate|inflation|\bcpi\b|\bppi\b|payroll|jobs report|gdp|treasury yield|retail sales/.test(t)) return "宏观";
  if (/earnings|quarterly results|revenue|profit|guidance|forecast|eps|quarterly report/.test(t)) return "财报";
  if (/merger|acqui|antitrust|sec |regulat|tariff|sanction|supreme court|white house|congress|lawsuit/.test(t)) return "政策";
  if (/launch|unveil|new product|chip|approval|clinical trial|fda|partnership|deal with/.test(t)) return "公司";
  if (/opec|crude|oil price|gold|bitcoin|crypto|semiconductor|banking sector/.test(t)) return "行业";
  return fallback;
}
function signal(title, category, isOfficial, source) {
  const trusted = /reuters|associated press|ap news|bloomberg|cnbc|wall street journal|financial times|marketwatch|yahoo finance|barron|investor.s business daily|fortune|business insider|federal reserve/i.test(source);
  const speculative = /\bwill\b|\bcould\b|\bwould\b|\bmay\b|\bmight\b|expects?|forecast|predict|odds/i.test(title);
  const high = isOfficial || (trusted && !speculative && /rate decision|rate cut|rate hike|fomc statement|\bcpi\b|nonfarm payroll|jobs report|inflation report|earnings (beat|miss|results)|strong earnings|quarterly results|raises guidance|cuts guidance|profit warning|merger|acquisition|fda approval|antitrust|tariff|sanction|bankruptcy|ceo steps down|shutdown|iea.*oil.*release/i.test(title));
  const reason = {财报:"业绩与预期",宏观:"利率与经济",政策:"规则与交易",公司:"公司基本面",行业:"板块传导",市场:"市场情绪"}[category] || "市场情绪";
  return {high, reason};
}
function relevant(title) {
  const noise = /(\bTSE:|\bNSE:|\bBSE:|₹|FY2[5-9]|\bIndia stocks\b|\bJapan stocks\b|\bIndian shares\b|\bEuropean shares\b|\bIndia.s rupee\b|\bWipro\b|\bAlan Greenspan\b|\bBangkok\b|\bAustralia names\b|live TV|live stream|video news|markets update|which .* should you buy|better buy|stock to buy|I.m \d\d years old|should I leave him|I lost my home|Jim Cramer|Lightning Round|Investing Club|Daily Open|would not bet|stock picks|buy rating|price target|how to invest|explainer|watch live|market outlook|weekly outlook|what to watch|stocks to watch|Fast Money.*talk|Don.t ditch|Make these moves|ICYMI:|What to led to|opportunities emerging|\bCramer:)/i;
  const event = /earnings|results|revenue|profit|guidance|launch|unveil|announce|approv|reject|cuts|raises|surge|fall|drop|rise|climb|plunge|rally|merger|acqui|deal|investigation|lawsuit|tariff|sanction|inflation|\bcpi\b|\bppi\b|jobs|payroll|gdp|fed\b|fomc|powell|rate|treasury|oil|opec|chip|fda|sec\b|white house|congress|s&p|nasdaq|dow jones|stocks?\b|shares?\b|bond|yield|product|forecast|data|bankrupt|recall|strike|shutdown|export|imports?/i;
  return !noise.test(title) && event.test(title);
}
function parse(xml, feedName, fallback, isOfficial) {
  const blocks = xml.match(/<item\b[\s\S]*?<\/item>/gi) || [];
  return blocks.slice(0, 100).map(block => {
    const title = field(block, "title");
    const link = field(block, "link");
    const date = field(block, "pubDate") || field(block, "published") || field(block, "dc:date");
    const published = new Date(date);
    let url;
    try { url = new URL(link); } catch { return null; }
    if (!/^https?:$/.test(url.protocol) || !title || !Number.isFinite(published.getTime())) return null;
    const source = field(block, "source") || feedName;
    const suffix = " - " + source;
    const cleanTitle = title.endsWith(suffix) ? title.slice(0, -suffix.length).trim() : title;
    if (!isOfficial && !relevant(cleanTitle)) return null;
    const category = classify(cleanTitle, isOfficial ? fallback : "市场");
    return {title:cleanTitle,url:url.href,published:published.toISOString(),source,category,...signal(cleanTitle,category,isOfficial,source)};
  }).filter(Boolean);
}
async function fetchFeed(url, name, category, isOfficial) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8500);
  try {
    const response = await fetch(url, {headers: {"user-agent":"MarketSignal/1.0 (public RSS reader)","accept":"application/rss+xml, application/xml, text/xml"},signal: controller.signal});
    if (!response.ok) throw Error("Feed " + response.status);
    return parse(await response.text(), name, category, isOfficial);
  } finally { clearTimeout(timer); }
}
async function getNews() {
  const jobs = searches.map(([category, query]) => fetchFeed("https://news.google.com/rss/search?q=" + encodeURIComponent(query) + "&hl=en-US&gl=US&ceid=US:en", "Google News", category, false));
  jobs.push(...official.map(([category,name,url]) => fetchFeed(url,name,category,true)));
  jobs.push(...editorial.map(([category,name,url]) => fetchFeed(url,name,category,false)));
  const settled = await Promise.allSettled(jobs);
  const cutoff = Date.now() - 24 * 3600000;
  const unique = new Map();
  for (const result of settled) {
    if (result.status !== "fulfilled") continue;
    for (const item of result.value) {
      const time = Date.parse(item.published);
      if (time < cutoff || time > Date.now() + 300000) continue;
      const key = item.title.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
      if (!key) continue;
      const old = unique.get(key);
      if (!old || (item.high && !old.high)) unique.set(key,item);
    }
  }
  return {items:[...unique.values()].sort((a,b) => Date.parse(b.published)-Date.parse(a.published)).slice(0,200),feeds:settled.length,errors:settled.filter(x => x.status === "rejected").length,fetchedAt:new Date().toISOString()};
}
const news = await getNews();
if (!news.items.length) throw Error("No recent headlines; preserving previous market-news.json");
writeFileSync(new URL("../market-news.json", import.meta.url), JSON.stringify(news, null, 2) + "\n");
console.log("Saved " + news.items.length + " headlines from " + (news.feeds - news.errors) + "/" + news.feeds + " feeds");
