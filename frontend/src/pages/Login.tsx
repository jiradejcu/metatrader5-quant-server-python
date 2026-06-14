import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "../hooks/useAuth";

function Login() {
  const { login, isLoggingIn, error } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await login({ username, password });
    } catch {
      // error is surfaced via useAuth's error state
    }
  };

  return (
    <div className="px-3 py-3 sm:px-5 sm:py-5 bg-[#f3f4f6] dark:bg-gray-900 min-h-screen flex items-center justify-center">
      <div className="w-full max-w-sm bg-white dark:bg-gray-800 p-6 rounded-xl shadow">
        <h1 className="text-base font-bold text-gray-700 dark:text-gray-200 mb-4 text-center">
          Arbitrage Bot Control
        </h1>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-600 dark:text-gray-300 mb-1">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-[#37BCED]"
              autoComplete="username"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-600 dark:text-gray-300 mb-1">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-[#37BCED]"
              autoComplete="current-password"
              required
            />
          </div>
          {error && <p className="text-sm text-red-500">{error}</p>}
          <button
            type="submit"
            disabled={isLoggingIn}
            className="w-full mt-2 py-2 px-4 rounded-lg font-semibold text-sm bg-gray-800 hover:bg-gray-700 dark:bg-gray-600 dark:hover:bg-gray-500 text-white transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoggingIn ? "Logging in..." : "Login"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default Login;
