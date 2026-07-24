export function PageHeader({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <header className="mb-6">
      <h2 className="text-lg font-medium">{title}</h2>
      <p className="mt-1 max-w-3xl text-sm leading-relaxed text-neutral-400">
        {description}
      </p>
    </header>
  );
}
