/* eslint-disable @typescript-eslint/no-explicit-any */
import "./App.css";
import { useState } from "react";
import LoginPage from "./pages/Login";
import DashboardPage from "./pages/Dashboard";
import { LayoutDashboard, LogOut, Menu, TrendingUp, User, X } from "lucide-react";

// The Router
const App: React.FC = () => {
  const [currentPage, setCurrentPage] = useState<'login' | 'dashboard' | 'settings'>('login');
  const [isSidebarOpen, setSidebarOpen] = useState(true);

  // Simple routing logic
  const renderPage = () => {
    switch(currentPage) {
      case 'dashboard': return <DashboardPage />;
      default: return <LoginPage onLogin={() => setCurrentPage('dashboard')} />;
    }
  };

  // If on login page, don't show the layout
  if (currentPage === 'login') {
    return <LoginPage onLogin={() => setCurrentPage('dashboard')} />;
  }

  return (
    <div className="min-h-screen bg-slate-50 flex">
      {/* Sidebar Navigation */}
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
            onClick={() => setCurrentPage('login')}
            className="w-full flex items-center gap-3 p-3 rounded-lg text-slate-400 hover:bg-red-900/20 hover:text-red-400 transition-colors"
          >
            <LogOut size={20} />
            {isSidebarOpen && <span>Logout</span>}
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
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