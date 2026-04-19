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
    <div className="fixed inset-0 w-screen h-screen flex items-center justify-center bg-slate-900 overflow-hidden">
      <div className="w-full max-w-md sm:max-w-lg lg:max-w-md bg-slate-800 rounded-2xl p-6 sm:p-8 lg:p-10 border border-slate-700 shadow-2xl mx-4 sm:mx-8">
        {/* Header */}
        <div className="text-center mb-8 sm:mb-10 lg:mb-12">
          <div className="inline-flex items-center justify-center w-14 h-14 sm:w-16 sm:h-16 lg:w-20 lg:h-20 bg-blue-600 rounded-xl mb-4 sm:mb-5 lg:mb-6">
            <TrendingUp className="text-white" size={32} />
          </div>
          <h1 className="text-2xl sm:text-3xl lg:text-4xl font-bold text-white leading-tight">Arbitrage Login</h1>
          <p className="text-sm sm:text-base lg:text-lg text-slate-400 mt-3 sm:mt-4 lg:mt-5">Enter your credentials to continue</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-5 sm:space-y-6">
          {/* Username */}
          <div>
            <label htmlFor="username" className="block text-xs sm:text-sm lg:text-base font-medium text-slate-300 mb-2.5 sm:mb-3">
              Username
            </label>
            <input
              id="username"
              type="text"
              placeholder="Enter username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={loginMutation.isPending}
              className="w-full bg-slate-900 border border-slate-700 text-white text-sm sm:text-base lg:text-lg p-3 sm:p-3.5 lg:p-4 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            />
          </div>

          {/* Password */}
          <div>
            <label htmlFor="password" className="block text-xs sm:text-sm lg:text-base font-medium text-slate-300 mb-2.5 sm:mb-3">
              Password
            </label>
            <input
              id="password"
              type="password"
              placeholder="Enter password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loginMutation.isPending}
              className="w-full bg-slate-900 border border-slate-700 text-white text-sm sm:text-base lg:text-lg p-3 sm:p-3.5 lg:p-4 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            />
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loginMutation.isPending}
            className="w-full bg-gradient-to-r from-blue-600 via-blue-500 to-blue-600 hover:from-blue-700 hover:via-blue-600 hover:to-blue-700 disabled:bg-slate-600/50 disabled:cursor-not-allowed text-white text-sm sm:text-base lg:text-lg font-bold py-3 sm:py-3.5 lg:py-4 rounded-lg transition-all duration-200 shadow-lg hover:shadow-2xl active:shadow-inner"
          >
            {loginMutation.isPending ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default LoginPage;