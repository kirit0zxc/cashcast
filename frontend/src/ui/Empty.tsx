// Честное пустое состояние: что отсутствует и что сделать.
export function Empty({ title, text }: { title: string; text?: string }) {
  return <div className="empty"><b>{title}</b>{text}</div>;
}
