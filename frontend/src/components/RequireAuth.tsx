"use client";

import { useAuth } from "@/context/AuthContext";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

type Props = {
  children: React.ReactNode;
  role?: string;
};

export default function RequireAuth({ children, role }: Props) {
  const { user, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (isLoading) return;

    if (!user) {
      router.replace(`/login?next=${encodeURIComponent(pathname || "/dashboard")}`);
      return;
    }

    if (role && user.role !== role) {
      router.replace("/dashboard");
    }
  }, [isLoading, user, role, router, pathname]);

  if (isLoading) {
    return <div className="min-h-screen flex items-center justify-center">Loading...</div>;
  }

  if (!user) {
    return <div className="min-h-screen flex items-center justify-center">Redirecting to login...</div>;
  }

  if (role && user.role !== role) {
    return <div className="min-h-screen flex items-center justify-center">Not authorized.</div>;
  }

  return <>{children}</>;
}

