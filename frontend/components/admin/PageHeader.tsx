export function PageHeader({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <header className="mb-6">
      <h2 className="text-lg font-medium text-ink-900 dark:text-ink-50">
        {title}
      </h2>
      <p className="mt-1 max-w-3xl text-sm leading-relaxed text-ink-500 dark:text-ink-300">
        {description}
      </p>
    </header>
  );
}
