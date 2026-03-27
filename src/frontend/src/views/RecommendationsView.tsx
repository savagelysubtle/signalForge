import { useSearchParams } from 'react-router-dom';
import { SearchScreen } from '../components/search/SearchScreen';
import { ResultsScreen } from '../components/search/ResultsScreen';
import { motion, AnimatePresence } from 'motion/react';

export function RecommendationsView() {
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('run');

  return (
    <AnimatePresence mode="wait">
      {runId ? (
        <motion.div
          key="results"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="h-full"
        >
          <ResultsScreen runId={runId} />
        </motion.div>
      ) : (
        <motion.div
          key="search"
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.98 }}
          transition={{ duration: 0.2 }}
          className="h-full"
        >
          <SearchScreen />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
