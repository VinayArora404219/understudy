import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { AdminPage } from "./pages/AdminPage";
import "./index.css";
import { CreatePage } from "./pages/CreatePage";
import { ExamplesPage } from "./pages/ExamplesPage";
import { JobPage } from "./pages/JobPage";
import { JudgeEntryPage } from "./pages/JudgeEntryPage";
import { LandingPage } from "./pages/LandingPage";
import { LibraryPage } from "./pages/LibraryPage";
import { NotFoundPage, PrivacyPage } from "./pages/StaticPages";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

const router = createBrowserRouter([
  { path: "/j/:token", element: <JudgeEntryPage /> },
  { path: "/welcome", element: <JudgeEntryPage /> },
  { path: "/admin", element: <AdminPage /> },
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <LandingPage /> },
      { path: "/create", element: <CreatePage /> },
      { path: "/examples", element: <ExamplesPage /> },
      { path: "/jobs/:id", element: <JobPage /> },
      { path: "/library", element: <LibraryPage /> },
      { path: "/privacy", element: <PrivacyPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
