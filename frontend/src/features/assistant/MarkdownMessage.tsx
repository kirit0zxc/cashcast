import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Ответ модели — недоверенный текст. HTML не исполняем, картинки не загружаем;
// ссылки открываются только по явному клику, без доступа к исходному окну.
function safeLink(url: string): string {
  if (url.startsWith("#")) return url;
  try {
    const parsed = new URL(url);
    return ["https:", "http:"].includes(parsed.protocol) ? parsed.href : "";
  } catch { return ""; }
}

export function MarkdownMessage({ text }: { text: string }) {
  return <div className="assistant-markdown">
    <Markdown remarkPlugins={[remarkGfm]} skipHtml urlTransform={safeLink}
      allowedElements={["p", "br", "strong", "em", "del", "ul", "ol", "li", "blockquote", "pre", "code",
        "h1", "h2", "h3", "h4", "h5", "h6", "hr", "a", "table", "thead", "tbody", "tr", "th", "td", "sup"]}
      components={{
        a: ({ href, children }) => href
          ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>,
        table: ({ children }) => <div className="scroll"><table className="ops">{children}</table></div>,
      }}>{text}</Markdown>
  </div>;
}
