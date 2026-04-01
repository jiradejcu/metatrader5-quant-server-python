/* eslint-disable @typescript-eslint/no-explicit-any */
import "./App.css";
import { useEffect, useState } from "react";
import LoginPage from "./pages/Login";
import DashboardPage from "./pages/Dashboard";
import { LayoutDashboard, LogOut, Menu, TrendingUp, User, X } from "lucide-react";
import { useLogout, useVerifyToken } from "./hooks/useAuth";
import type { AuthError } from "./interfaces/auth.interface";
import { useAllBots } from "./hooks/all-bot";

const App: React.FC = () => {
  const [currentPage, setCurrentPage] = useState<'login' | 'dashboard' | 'settings'>('login');
  const [isSidebarOpen, setSidebarOpen] = useState(true);
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
      // On logout error, stay on dashboard (token still valid)
      console.error('Logout error:', error.message);
    }
  );

  const handleLogout = () => {
    logoutMutation.mutate();
  };

  const renderPage = () => {
    switch(currentPage) {
      case 'dashboard': return <DashboardPage />;
      // TODO: for adding new pages in the future
      default: return <LoginPage onLogin={() => setCurrentPage('dashboard')} />;
    }
  };

  if (isVerifying) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900">
        <div className="text-white">Verifying session...</div>
      </div>
    );
  }

  if (currentPage === 'login') {
    return <LoginPage onLogin={() => setCurrentPage('dashboard')} />;
  }

  return (
    <div className="min-h-screen bg-slate-50 flex">
      {/* Sidebar */}
      <aside className={`${isSidebarOpen ? 'w-64' : 'w-20'} bg-slate-900 transition-all duration-300 flex flex-col`}>
        <div className="p-6 flex items-center gap-3">
          <TrendingUp className="text-blue-500" />
          {isSidebarOpen && <span className="text-white font-bold text-lg">MT5 Quant</span>}
        </div>

        <nav className="flex-1 px-4 space-y-2 mt-4">
          <button 
            onClick={() => setCurrentPage('dashboard')}
            className={`w-full flex items-center gap-3 p-3 rounded-lg transition-colors ${currentPage === 'dashboard' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'}`}
          >
            <LayoutDashboard size={20} />
            {isSidebarOpen && <span>Dashboard</span>}
          </button>
        </nav>

        <div className="p-4 border-t border-slate-800">
          <button 
            onClick={handleLogout}
            disabled={logoutMutation.isPending}
            className="w-full flex items-center gap-3 p-3 rounded-lg text-slate-400 hover:bg-red-900/20 hover:text-red-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <LogOut size={20} />
            {isSidebarOpen && <span>{logoutMutation.isPending ? 'Logging out...' : 'Logout'}</span>}
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col h-screen overflow-hidden">
        <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-8">
          <button onClick={() => setSidebarOpen(!isSidebarOpen)} className="text-slate-500">
            {isSidebarOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
          <div className="flex items-center gap-4">
            <div className="text-right hidden sm:block">
              <div className="text-sm font-bold text-slate-900">Quant Trader</div>
              <div className="text-xs text-slate-500">Pro Account</div>
            </div>
            <div className="w-10 h-10 bg-slate-200 rounded-full flex items-center justify-center">
              <User className="text-slate-500" size={20} />
            </div>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto">
          {renderPage()}
        </div>
      </main>
    </div>
  );
};

export default App;