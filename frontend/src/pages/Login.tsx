import { 
  TrendingUp,
} from 'lucide-react';
import { useState } from 'react';
import { useLogin } from '../hooks/useAuth';
import type { AuthError, AuthResponse } from '../interfaces/auth.interface';
import { useAllBots } from '../hooks/all-bot';

const LoginPage = ({ onLogin }: { onLogin: () => void }) => {
  const { 
    // use dev instance for handling access token and auth, since it's the only one that requires auth
    botUrlDev
  } = useAllBots()
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const onSuccess = (data: AuthResponse) => {
    alert(`Welcome, ${data.user?.display_name || 'User'}!`);

    setUsername('');
    setPassword('');

    setTimeout(() => {
      onLogin();
    }, 500);
  }
  const onError = (error: AuthError) => {
      alert(error.message || 'Login failed. Please try again.');
    }

  const loginMutation = useLogin(
    botUrlDev,
    onSuccess,
    onError,
  );

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    if (!username || !password) {
      alert('Please enter both username and password');
      return;
    }

    loginMutation.mutate({ username, password });
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 p-4">
      <div className="w-full max-w-md bg-slate-800 rounded-2xl p-8 border border-slate-700 shadow-2xl">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-600 rounded-xl mb-4">
            <TrendingUp className="text-white" size={32} />
          </div>
          <h1 className="text-2xl font-bold text-white">Quant Server Login</h1>
          <p className="text-slate-400 mt-2">Enter your credentials to continue</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-slate-300 mb-2">
              Username
            </label>
            <input
              id="username"
              type="text"
              placeholder="Enter username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={loginMutation.isPending}
              className="w-full bg-slate-900 border border-slate-700 text-white p-3 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-slate-300 mb-2">
              Password
            </label>
            <input
              id="password"
              type="password"
              placeholder="Enter password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loginMutation.isPending}
              className="w-full bg-slate-900 border border-slate-700 text-white p-3 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>

          <button
            type="submit"
            disabled={loginMutation.isPending}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 disabled:cursor-not-allowed text-white font-bold py-3 rounded-lg transition-colors"
          >
            {loginMutation.isPending ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <div className="mt-6 text-center text-sm text-slate-400">
          <p>Demo Credentials:</p>
          <p className="text-slate-500 mt-2">Username: admin</p>
          <p className="text-slate-500">Password: (check .env)</p>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;