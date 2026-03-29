import { 
  TrendingUp,
} from 'lucide-react';

/** * ARCHITECTURAL NOTE FOR YOUR LOCAL PROJECT:
 * 1. Create a folder: src/pages/
 * 2. Move your login code to: src/pages/LoginPage.tsx
 * 3. Move your dashboard code to: src/pages/DashboardPage.tsx
 * 4. Your App.tsx will then become the "Traffic Controller"
 */

// --- PAGE 1: LOGIN PAGE ---
const LoginPage = ({ onLogin }: { onLogin: () => void }) => (
  <div className="min-h-screen flex items-center justify-center bg-slate-900 p-4">
    <div className="w-full max-w-md bg-slate-800 rounded-2xl p-8 border border-slate-700 shadow-2xl">
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-600 rounded-xl mb-4">
          <TrendingUp className="text-white" size={32} />
        </div>
        <h1 className="text-2xl font-bold text-white">Quant Server Login</h1>
        <p className="text-slate-400 mt-2">Enter your credentials to continue</p>
      </div>
      <div className="space-y-4">
        <input 
          type="email" 
          placeholder="Email" 
          className="w-full bg-slate-900 border border-slate-700 text-white p-3 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
        />
        <input 
          type="password" 
          placeholder="Password" 
          className="w-full bg-slate-900 border border-slate-700 text-white p-3 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button 
          onClick={onLogin}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 rounded-lg transition-colors"
        >
          Sign In
        </button>
      </div>
    </div>
  </div>
);

export default LoginPage;