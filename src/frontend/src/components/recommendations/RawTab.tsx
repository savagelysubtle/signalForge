interface RawTabProps {
  data: any;
}

export function RawTab({ data }: RawTabProps) {
  return (
    <div className="p-4 h-full overflow-auto">
      <pre className="text-xs text-text-secondary bg-bg-tertiary p-4 rounded-lg border border-border overflow-x-auto">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}
