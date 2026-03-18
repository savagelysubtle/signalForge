import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { ProtectedRoute } from "./components/auth/ProtectedRoute";
import { LoginPage } from "./components/auth/LoginPage";
import { MainLayout } from "./components/layout/MainLayout";
import { RecommendationsView } from "./views/RecommendationsView";
import { HistoryView } from "./views/HistoryView";
import { StrategiesView } from "./views/StrategiesView";
import { InsightsView } from "./views/InsightsView";
import { SettingsView } from "./views/SettingsView";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <MainLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<RecommendationsView />} />
            <Route path="history" element={<HistoryView />} />
            <Route path="strategies" element={<StrategiesView />} />
            <Route path="insights" element={<InsightsView />} />
            <Route path="settings" element={<SettingsView />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
