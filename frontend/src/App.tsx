import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ApiError } from "./lib/api";
import { SessionProvider, useIsMobile, useSession } from "./lib/session";
import { Skeleton, ToastProvider } from "./components/ui";
import DesktopShell from "./pages/DesktopShell";
import Login from "./pages/Login";
import { TourProvider } from "./tour/TourProvider";

const TourOverlay = lazy(() => import("./tour/TourOverlay"));

const Overview = lazy(() => import("./pages/Overview"));
const LiveMap = lazy(() => import("./pages/LiveMap"));
const Events = lazy(() => import("./pages/Events"));
const EventPage = lazy(() => import("./pages/EventPage"));
const Facilities = lazy(() => import("./pages/Facilities"));
const FacilityPage = lazy(() => import("./pages/FacilityPage"));
const Alerts = lazy(() => import("./pages/Alerts"));
const Watchlists = lazy(() => import("./pages/Watchlists"));
const Reports = lazy(() => import("./pages/Reports"));
const Analytics = lazy(() => import("./pages/Analytics"));
const DataSources = lazy(() => import("./pages/DataSources"));
const SystemHealth = lazy(() => import("./pages/SystemHealth"));
const Settings = lazy(() => import("./pages/Settings"));
const MobileApp = lazy(() => import("./mobile/MobileApp"));

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (n, e) => !(e instanceof ApiError && [400, 401, 403, 404, 422].includes(e.status)) && n < 2,
    },
  },
});

function Gate() {
  const { user, loading, isDemo } = useSession();
  const mobile = useIsMobile();
  if (loading) return <div className="auth"><div style={{ width: 240 }}><Skeleton lines={3} /></div></div>;
  if (!user) return <Login />;
  const fallback = <div className="page"><Skeleton lines={6} /></div>;
  const tour = isDemo ? <Suspense fallback={null}><TourOverlay /></Suspense> : null;
  if (mobile) return <><Suspense fallback={fallback}><MobileApp /></Suspense>{tour}</>;
  return (
    <>
    {tour}
    <Routes>
      <Route element={<DesktopShell />}>
        <Route index element={<Navigate to="/map" replace />} />
        <Route path="/overview" element={<Suspense fallback={fallback}><Overview /></Suspense>} />
        <Route path="/map" element={<Suspense fallback={fallback}><LiveMap /></Suspense>} />
        <Route path="/events" element={<Suspense fallback={fallback}><Events /></Suspense>} />
        <Route path="/events/:ref" element={<Suspense fallback={fallback}><EventPage /></Suspense>} />
        <Route path="/facilities" element={<Suspense fallback={fallback}><Facilities /></Suspense>} />
        <Route path="/facilities/:id" element={<Suspense fallback={fallback}><FacilityPage /></Suspense>} />
        <Route path="/alerts" element={<Suspense fallback={fallback}><Alerts /></Suspense>} />
        <Route path="/watchlists" element={<Suspense fallback={fallback}><Watchlists /></Suspense>} />
        <Route path="/reports" element={<Suspense fallback={fallback}><Reports /></Suspense>} />
        <Route path="/analytics" element={<Suspense fallback={fallback}><Analytics /></Suspense>} />
        <Route path="/sources" element={<Suspense fallback={fallback}><DataSources /></Suspense>} />
        <Route path="/system" element={<Suspense fallback={fallback}><SystemHealth /></Suspense>} />
        <Route path="/settings" element={<Suspense fallback={fallback}><Settings /></Suspense>} />
        <Route path="*" element={<div className="page"><h1>Not found</h1><p className="muted">This page does not exist.</p></div>} />
      </Route>
    </Routes>
    </>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <SessionProvider>
          <ToastProvider>
            <TourProvider>
              <Gate />
            </TourProvider>
          </ToastProvider>
        </SessionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
