import clsx from 'clsx';

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={clsx('animate-pulse rounded bg-bg-steel', className)}
      aria-hidden="true"
    />
  );
}

export function TickerCardSkeleton() {
  return (
    <div className="p-3.5 border border-border-gutter rounded-lg bg-bg-concrete space-y-2.5">
      <div className="flex justify-between items-start">
        <div className="space-y-1.5">
          <Skeleton className="h-5 w-20" />
          <Skeleton className="h-3 w-32" />
        </div>
        <Skeleton className="h-5 w-12 rounded-full" />
      </div>
      <Skeleton className="h-3 w-16" />
      <Skeleton className="h-8 w-full" />
    </div>
  );
}

export function TabContentSkeleton() {
  return (
    <div className="p-6 space-y-4">
      <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6 space-y-3">
        <div className="flex justify-between items-center">
          <Skeleton className="h-10 w-24 rounded-lg" />
          <Skeleton className="h-10 w-16" />
        </div>
        <Skeleton className="h-2 w-full rounded-full" />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="bg-bg-void rounded-lg p-3 border border-border-gutter space-y-1.5">
            <Skeleton className="h-3 w-12" />
            <Skeleton className="h-4 w-16" />
          </div>
        ))}
      </div>
      <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6 space-y-2">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-4/5" />
        <Skeleton className="h-4 w-3/4" />
      </div>
    </div>
  );
}
