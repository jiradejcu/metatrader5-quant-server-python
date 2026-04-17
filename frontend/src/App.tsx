/* eslint-disable @typescript-eslint/no-explicit-any */
import "./App.css";
import { useEffect, useState } from "react";
import LoginPage from "./pages/Login";
import DashboardPage from "./pages/Dashboard";
import { LogOut, TrendingUp } from "lucide-react";
import { useLogout, useVerifyToken } from "./hooks/useAuth";
import type { AuthError } from "./interfaces/auth.interface";
import { useAllBots } from "./hooks/all-bot";

function App() {
  const [currentPage, setCurrentPage] = useState<'login' | 'dashboard'>('login');
  const { botUrlDev } = useAllBots();

  // Verify token on mount
  const { data: verifyData, isLoading: isVerifying, isError: verifyError } = useVerifyToken(botUrlDev);

  useEffect(() => {
    if (!isVerifying) {
      if (verifyError || !verifyData) {
        setCurrentPage('login');
      } else {
        setCurrentPage('dashboard');
      }
    }
  }, [isVerifying, verifyData, verifyError]);

  const logoutMutation = useLogout(
    botUrlDev,
    () => {
      setCurrentPage('login');
    },
    (error: AuthError) => {
      console.error('Logout error:', error.message);
    }
  );

  if (isVerifying) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-slate-900">
        <div className="text-white">Verifying session...</div>
      </div>
    );
  }

  if (currentPage === 'login') {
    return <LoginPage onLogin={() => setCurrentPage('dashboard')} />;
  }

  return (
    <div className="flex flex-col min-h-screen bg-[#f3f4f6] dark:bg-gray-900">
      {/* Header */}
      <header className="sticky top-0 z-20 bg-white dark:bg-gray-800 shadow px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="text-blue-500" size={20} />
          <span className="text-base font-bold text-gray-700 dark:text-gray-200">
            MT5 Quant
          </span>
        </div>
        <button
          onClick={() => logoutMutation.mutate()}
          disabled={logoutMutation.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-slate-500 hover:bg-red-100 hover:text-red-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <LogOut size={16} />
          <span>{logoutMutation.isPending ? 'Logging out...' : 'Logout'}</span>
        </button>
      </header>

      {/* Dashboard Content */}
      <main className="flex-1">
        <DashboardPage />
      </main>
    </div>
  );
};

export default App;
