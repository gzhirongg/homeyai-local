"use client";

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import API_BASE from '@/lib/apiBase';
import {
  getStoredAdminPreviewSubscription,
  setStoredAdminPreviewSubscription,
  subscriptionAwareHeaders,
  type AdminPreviewSubscription,
} from '@/lib/subscriptionPreview';

interface User {
  email: string;
  full_name: string;
  role: string;
  remaining_valuations?: number | null;
}

interface AuthContextType {
  user: User | null;
  login: (email: string, pass: string) => Promise<void>;
  register: (email: string, pass: string, name: string) => Promise<void>;
  updateProfile: (fullName: string) => Promise<void>;
  refreshProfile: () => Promise<void>;
  logout: () => void;
  deleteAccount: () => Promise<void>;
  isLoading: boolean;
  /** Admin-only: preview free vs premium UI/API without changing `users.role`. */
  adminPreviewSubscription: AdminPreviewSubscription | null;
  setAdminPreviewSubscription: (value: AdminPreviewSubscription | null) => void;
  /** Tier used for subscriber UX (admin + preview overrides real `user.role`). */
  effectiveSubscriptionRole: string | null;
  /** True when premium-only features should appear enabled for this session. */
  isPremiumExperience: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [adminPreviewSubscription, setAdminPreviewSubscriptionState] = useState<AdminPreviewSubscription | null>(null);
  const router = useRouter();

  const setAdminPreviewSubscription = useCallback((value: AdminPreviewSubscription | null) => {
    setStoredAdminPreviewSubscription(value);
    setAdminPreviewSubscriptionState(value);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    setStoredAdminPreviewSubscription(null);
    setAdminPreviewSubscriptionState(null);
    setUser(null);
    router.push('/');
  }, [router]);

  const refreshProfile = useCallback(async () => {
    const token = localStorage.getItem('token');
    if (!token) return;

    const response = await fetch(`${API_BASE}/api/user/profile`, {
      method: 'GET',
      headers: subscriptionAwareHeaders(token),
    });

    if (!response.ok) {
      if (response.status === 401 || response.status === 403) logout();
      return;
    }

    const freshUser = (await response.json()) as User;
    localStorage.setItem('user', JSON.stringify(freshUser));
    setUser(freshUser);
    if (freshUser.role !== 'admin') {
      setStoredAdminPreviewSubscription(null);
      setAdminPreviewSubscriptionState(null);
    } else {
      setAdminPreviewSubscriptionState(getStoredAdminPreviewSubscription());
    }
  }, [logout]);

  useEffect(() => {
    const storedUser = localStorage.getItem('user');
    const token = localStorage.getItem('token');
    if (storedUser && token) {
      try {
        const parsed = JSON.parse(storedUser) as User;
        setUser(parsed);
        if (parsed.role === 'admin') {
          setAdminPreviewSubscriptionState(getStoredAdminPreviewSubscription());
        }
      } catch {
        setUser(null);
      }
    }
    setIsLoading(false);
    refreshProfile().catch(() => {});
  }, [refreshProfile]);

  useEffect(() => {
    if (!user) {
      setAdminPreviewSubscriptionState(null);
      return;
    }
    if (user.role !== 'admin') {
      setStoredAdminPreviewSubscription(null);
      setAdminPreviewSubscriptionState(null);
    } else {
      setAdminPreviewSubscriptionState(getStoredAdminPreviewSubscription());
    }
  }, [user?.role, user?.email]);

  const login = async (email: string, password: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Login failed');
      }

      const data = await response.json();
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(data.user));
      setUser(data.user);
      if (data.user?.role === 'admin') {
        setAdminPreviewSubscriptionState(getStoredAdminPreviewSubscription());
      } else {
        setStoredAdminPreviewSubscription(null);
        setAdminPreviewSubscriptionState(null);
      }
      router.push('/dashboard');
    } catch (error) {
      console.error('Login error:', error);
      throw error;
    }
  };

  const register = async (email: string, password: string, full_name: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, full_name }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Registration failed');
      }

      const data = await response.json();
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(data.user));
      setUser(data.user);
      setStoredAdminPreviewSubscription(null);
      setAdminPreviewSubscriptionState(null);
      router.push('/dashboard');
    } catch (error) {
      console.error('Registration error:', error);
      throw error;
    }
  };

  const updateProfile = async (full_name: string) => {
    const token = localStorage.getItem('token');
    if (!token) {
      logout();
      throw new Error('Not authenticated');
    }
    if (!user) {
      throw new Error('No user loaded');
    }

    const response = await fetch(`${API_BASE}/api/user/profile`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...subscriptionAwareHeaders(token),
      },
      body: JSON.stringify({ full_name }),
    });

    if (!response.ok) {
      let detail = 'Failed to update profile';
      try {
        const error = await response.json();
        detail = error.detail || detail;
      } catch {
        // ignore json parse errors
      }
      throw new Error(detail);
    }

    const nextUser = { ...user, full_name };
    localStorage.setItem('user', JSON.stringify(nextUser));
    setUser(nextUser);
  };

  const deleteAccount = async () => {
    const token = localStorage.getItem('token');
    if (!token) throw new Error('Not authenticated');

    const response = await fetch(`${API_BASE}/api/user/profile`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!response.ok) {
      throw new Error('Failed to delete account');
    }

    logout();
  };

  const effectiveSubscriptionRole = useMemo(() => {
    if (!user) return null;
    if (user.role === 'admin' && adminPreviewSubscription) {
      return adminPreviewSubscription;
    }
    return user.role;
  }, [user, adminPreviewSubscription]);

  const isPremiumExperience = effectiveSubscriptionRole === 'premium';

  return (
    <AuthContext.Provider
      value={{
        user,
        login,
        register,
        updateProfile,
        refreshProfile,
        logout,
        deleteAccount,
        isLoading,
        adminPreviewSubscription,
        setAdminPreviewSubscription,
        effectiveSubscriptionRole,
        isPremiumExperience,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
