import { Link, Route, Routes } from "react-router-dom";

import { ErrorBoundary } from "./components/Common";
import { Header } from "./components/Header";
import { IncidentDetail, IncidentList } from "./routes/Incidents";
import { InspectionHistory } from "./routes/InspectionHistory";
import { InspectionWorkspace } from "./routes/InspectionWorkspace";
import { Intake } from "./routes/Intake";
import { Landing } from "./routes/Landing";
import { NotFound, SystemStatusPage } from "./routes/SystemStatus";

function HomePage() {
  return <Intake mode="home" />;
}

function IndustrialPage() {
  return <Intake mode="industrial" />;
}

export default function App() {
  return (
    <div className="flex min-h-screen flex-col bg-mist/30">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-30 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-navy"
      >
        Skip to main content
      </a>
      <Header />
      <main id="main" className="flex min-h-0 flex-1 flex-col">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/home" element={<HomePage />} />
            <Route path="/industrial" element={<IndustrialPage />} />
            <Route path="/inspections" element={<InspectionHistory />} />
            <Route path="/inspections/:inspectionId" element={<InspectionWorkspace />} />
            <Route path="/incidents" element={<IncidentList />} />
            <Route path="/incidents/:incidentId" element={<IncidentDetail />} />
            <Route path="/system" element={<SystemStatusPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </ErrorBoundary>
      </main>
      <footer className="border-t border-mist bg-white px-4 py-4 text-center text-xs text-slate">
        <p>
          SightOps — An Agentic Visual Reliability Engineer · Yabloko Labs · OpenCV AI Competition
          2026 ·{" "}
          <Link to="/system" className="font-medium text-brand underline">
            system status
          </Link>
        </p>
        <p className="mt-1">
          Decision support only. SightOps does not control machinery; consequential actions are
          simulated and require human approval.
        </p>
      </footer>
    </div>
  );
}
