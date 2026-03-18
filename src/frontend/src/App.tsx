import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { MainLayout } from './components/layout/MainLayout';
import { RecommendationsView } from './views/RecommendationsView';
import { HistoryView } from './views/HistoryView';
import { StrategiesView } from './views/StrategiesView';
import { InsightsView } from './views/InsightsView';
import { SettingsView } from './views/SettingsView';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<MainLayout />}>
          <Route index element={<RecommendationsView />} />
          <Route path="history" element={<HistoryView />} />
          <Route path="strategies" element={<StrategiesView />} />
          <Route path="insights" element={<InsightsView />} />
          <Route path="settings" element={<SettingsView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
