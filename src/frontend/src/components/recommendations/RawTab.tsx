import type { PipelineResult } from '../../types';

interface RawTabProps {
  data: PipelineResult;
}

export function RawTab({ data }: RawTabProps) {
  return (
    <div className="p-4 h-full overflow-auto">
      <pre className="text-xs text-text-secondary font-display bg-bg-concrete p-4 rounded-lg border border-border-gutter overflow-x-auto">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}
