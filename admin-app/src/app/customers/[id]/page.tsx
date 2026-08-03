"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Mail, Globe, Plus, Users, Trash2, RotateCcw, AlertTriangle, FileText, Briefcase, MapPin, Clock, Loader2 } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// V2 backend base — admin endpoints ported to /api/v2/admin.

const API_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8004";
const CACHE_DURATION = 3 * 60 * 1000; // 3 minutes
const CACHE_VERSION = 4;

interface SlackFeatures {
  calendar_notifications: boolean;
  assistant_read: boolean;
  assistant_write: boolean;
}

interface Organization {
  id: string;
  name: string;
  domain: string | null;
  description: string | null;
  slack_features: SlackFeatures | null;
  auto_join_enabled: boolean | null;
  blocked_domains: string[] | null;
  created_at: string;
  updated_at: string;
}

interface Profile {
  id: string;
  email: string;
  full_name: string;
  organization_id: string;
  is_staff: boolean;
  created_at: string;
  deleted_at: string | null;
}

interface Requisition {
  id: string;
  organization_id: string;
  role_title: string;
  role_location: string;
  experience_min_years: number;
  experience_max_years: number | null;
  experience_display: string;
  status: string;
  intake_notes: string | null;
  job_description: string | null;
  must_have_skills: string[];
  good_to_have_skills: string[];
  created_at: string;
  updated_at: string;
}

interface CacheData {
  organization: Organization;
  users: Profile[];
  deletedUsers: Profile[];
  requisitions: Requisition[];
  deletedRequisitions: Requisition[];
  slackFeatures: SlackFeatures;
  timestamp: number;
  version?: number;
}

type Tab = "users" | "requisitions";

function DetailSkeleton() {
  return (
    <div className="animate-pulse space-y-4">
      <div className="h-5 bg-secondary rounded w-1/3" />
      <div className="h-4 bg-secondary rounded w-1/2" />
      <div className="h-5 bg-secondary rounded w-1/4 mt-4" />
      <div className="h-4 bg-secondary rounded w-2/3" />
    </div>
  );
}

function UserRowSkeleton() {
  return (
    <tr className="animate-pulse">
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-secondary" />
          <div className="h-4 bg-secondary rounded w-24" />
        </div>
      </td>
      <td className="px-4 py-3"><div className="h-4 bg-secondary rounded w-40" /></td>
      <td className="px-4 py-3"><div className="h-5 bg-secondary rounded-full w-20" /></td>
      <td className="px-4 py-3"><div className="h-4 bg-secondary rounded w-20" /></td>
      <td className="px-4 py-3"><div className="h-4 bg-secondary rounded w-8 ml-auto" /></td>
    </tr>
  );
}

function RequisitionSkeleton() {
  return (
    <div className="border border-border rounded-lg p-4 animate-pulse">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2">
            <div className="h-5 bg-secondary rounded w-48" />
            <div className="h-5 bg-secondary rounded w-20" />
          </div>
          <div className="flex items-center gap-4">
            <div className="h-4 bg-secondary rounded w-32" />
            <div className="h-4 bg-secondary rounded w-24" />
            <div className="h-4 bg-secondary rounded w-20" />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-8 bg-secondary rounded w-24" />
          <div className="h-8 bg-secondary rounded w-8" />
        </div>
      </div>
    </div>
  );
}

export default function OrganizationDetailPage() {
  const params = useParams();
  const router = useRouter();
  const orgId = params.id as string;

  const [organization, setOrganization] = useState<Organization | null>(null);
  const [users, setUsers] = useState<Profile[]>([]);
  const [deletedUsers, setDeletedUsers] = useState<Profile[]>([]);
  const [requisitions, setRequisitions] = useState<Requisition[]>([]);
  const [deletedRequisitions, setDeletedRequisitions] = useState<Requisition[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<Tab>("users");

  const [showAddUser, setShowAddUser] = useState(false);
  const [newUserName, setNewUserName] = useState("");
  const [newUserEmail, setNewUserEmail] = useState("");
  const [addingUser, setAddingUser] = useState(false);
  const [addUserError, setAddUserError] = useState("");
  const [actionUserId, setActionUserId] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [resendingUserId, setResendingUserId] = useState<string | null>(null);

  const [showAddRequisition, setShowAddRequisition] = useState(false);
  const [newReqTitle, setNewReqTitle] = useState("");
  const [newReqLocation, setNewReqLocation] = useState("");
  const [newReqMinYears, setNewReqMinYears] = useState(0);
  const [newReqMaxYears, setNewReqMaxYears] = useState<number | null>(null);
  const [noMaxYears, setNoMaxYears] = useState(false);
  const [addingRequisition, setAddingRequisition] = useState(false);
  const [addReqError, setAddReqError] = useState("");
  const [actionReqId, setActionReqId] = useState<string | null>(null);
  const [deleteReqConfirmId, setDeleteReqConfirmId] = useState<string | null>(null);

  const [slackFeatures, setSlackFeatures] = useState<SlackFeatures>({
    calendar_notifications: true,
    assistant_read: false,
    assistant_write: false,
  });
  const [savingSlackFeatures, setSavingSlackFeatures] = useState(false);

  const [autoJoinEnabled, setAutoJoinEnabled] = useState(true);
  const [blockedDomains, setBlockedDomains] = useState<string[]>([]);
  const [savingCalIntel, setSavingCalIntel] = useState(false);

  const [userFeatures, setUserFeatures] = useState<Record<string, SlackFeatures | null>>({});
  const [savingUserFeatureId, setSavingUserFeatureId] = useState<string | null>(null);

  const getCacheKey = useCallback(() => `openrecruiting_org_${orgId}_cache`, [orgId]);

  const loadCachedData = useCallback(() => {
    try {
      const cached = sessionStorage.getItem(getCacheKey());
      if (cached) {
        const data: CacheData = JSON.parse(cached);
        if (data.version !== CACHE_VERSION) {
          sessionStorage.removeItem(getCacheKey());
          return false;
        }
        const isExpired = Date.now() - data.timestamp > CACHE_DURATION;
        setOrganization(data.organization);
        setUsers(data.users);
        setDeletedUsers(data.deletedUsers);
        setRequisitions(data.requisitions);
        setDeletedRequisitions(data.deletedRequisitions);
        if (data.slackFeatures) {
          setSlackFeatures(data.slackFeatures);
        }
        if (data.organization.auto_join_enabled !== null && data.organization.auto_join_enabled !== undefined) {
          setAutoJoinEnabled(data.organization.auto_join_enabled);
        }
        if (data.organization.blocked_domains) {
          setBlockedDomains(data.organization.blocked_domains);
        }
        setIsLoading(false);
        return !isExpired;
      }
    } catch {}
    return false;
  }, [getCacheKey]);

  const saveCache = useCallback((data: Omit<CacheData, 'timestamp' | 'version'>) => {
    try {
      const cacheData: CacheData = { ...data, timestamp: Date.now(), version: CACHE_VERSION };
      sessionStorage.setItem(getCacheKey(), JSON.stringify(cacheData));
    } catch {}
  }, [getCacheKey]);

  const fetchData = useCallback(async (showRefreshing = false) => {
    try {
      if (showRefreshing) setIsRefreshing(true);

      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const [orgResponse, usersResponse, deletedUsersResponse, reqsResponse, deletedReqsResponse] = await Promise.all([
        fetch(`${API_V2_URL}/api/v2/admin/organizations/${orgId}`, {
          headers: { "Authorization": `Bearer ${session.access_token}` }
        }),
        fetch(`${API_V2_URL}/api/v2/admin/organizations/${orgId}/users`, {
          headers: { "Authorization": `Bearer ${session.access_token}` }
        }),
        fetch(`${API_V2_URL}/api/v2/admin/organizations/${orgId}/users/deleted`, {
          headers: { "Authorization": `Bearer ${session.access_token}` }
        }),
        fetch(`${API_V2_URL}/api/v2/admin/requisitions/organizations/${orgId}`, {
          headers: { "Authorization": `Bearer ${session.access_token}` }
        }),
        fetch(`${API_V2_URL}/api/v2/admin/requisitions/organizations/${orgId}/deleted`, {
          headers: { "Authorization": `Bearer ${session.access_token}` }
        })
      ]);

      if (!orgResponse.ok) {
        if (orgResponse.status === 404) {
          setError("Organization not found");
        } else {
          throw new Error("Failed to fetch organization");
        }
        return;
      }

      const orgData = await orgResponse.json();
      setOrganization(orgData);
      const features = orgData.slack_features || {
        calendar_notifications: true,
        assistant_read: false,
        assistant_write: false,
      };
      setSlackFeatures(features);
      if (orgData.auto_join_enabled !== null && orgData.auto_join_enabled !== undefined) {
        setAutoJoinEnabled(orgData.auto_join_enabled);
      }
      if (orgData.blocked_domains) {
        setBlockedDomains(orgData.blocked_domains);
      }

      let usersData: Profile[] = [];
      let deletedUsersData: Profile[] = [];
      let reqsData: Requisition[] = [];
      let deletedReqsData: Requisition[] = [];

      if (usersResponse.ok) {
        const data = await usersResponse.json();
        usersData = data.users || [];
        setUsers(usersData);

        const connResponse = await fetch(`${API_V2_URL}/api/v2/admin/organizations/${orgId}/slack-connections`, {
          headers: { "Authorization": `Bearer ${session.access_token}` }
        });
        if (connResponse.ok) {
          const conns = await connResponse.json();
          const featuresMap: Record<string, SlackFeatures | null> = {};
          for (const conn of conns) {
            featuresMap[conn.profile_id] = conn.user_slack_features || null;
          }
          setUserFeatures(featuresMap);
        }
      }

      if (deletedUsersResponse.ok) {
        const data = await deletedUsersResponse.json();
        deletedUsersData = data.users || [];
        setDeletedUsers(deletedUsersData);
      }

      if (reqsResponse.ok) {
        const data = await reqsResponse.json();
        reqsData = data.requisitions || [];
        setRequisitions(reqsData);
      }

      if (deletedReqsResponse.ok) {
        const data = await deletedReqsResponse.json();
        deletedReqsData = data.requisitions || [];
        setDeletedRequisitions(deletedReqsData);
      }

      saveCache({
        organization: orgData,
        users: usersData,
        deletedUsers: deletedUsersData,
        requisitions: reqsData,
        deletedRequisitions: deletedReqsData,
        slackFeatures: features,
      });

    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [orgId, router, saveCache]);

  useEffect(() => {
    const hasFreshCache = loadCachedData();
    if (hasFreshCache) {
      fetchData(true);
    } else {
      fetchData(false);
    }
  }, [loadCachedData, fetchData]);

  const handleAddUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUserName.trim() || !newUserEmail.trim()) return;

    setAddingUser(true);
    setAddUserError("");

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/organizations/${orgId}/users`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${session.access_token}`
        },
        body: JSON.stringify({
          email: newUserEmail.trim().toLowerCase(),
          full_name: newUserName.trim(),
          role: "recruiter"
        })
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to add user");
      }

      const result = await response.json();
      const newUser: Profile = {
        id: result.user_id,
        email: result.email,
        full_name: newUserName.trim(),
        organization_id: orgId,
        is_staff: false,
        created_at: new Date().toISOString(),
        deleted_at: null,
      };
      const updatedUsers = [...users, newUser];
      setUsers(updatedUsers);
      if (organization) {
        saveCache({
          organization,
          users: updatedUsers,
          deletedUsers,
          requisitions,
          deletedRequisitions,
          slackFeatures,
        });
      }

      setNewUserName("");
      setNewUserEmail("");
      setShowAddUser(false);

    } catch (err) {
      setAddUserError(err instanceof Error ? err.message : "Failed to add user");
    } finally {
      setAddingUser(false);
    }
  };

  const handleResetInvite = async (userId: string) => {
    setResendingUserId(userId);

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/users/${userId}/reset-invite`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${session.access_token}`
        }
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to reset invitation");
      }

      const result = await response.json();
      const updatedUsers = users.map(u =>
        u.id === userId
          ? { ...u, id: result.user_id }
          : u
      );
      setUsers(updatedUsers);
      if (organization) {
        saveCache({
          organization,
          users: updatedUsers,
          deletedUsers,
          requisitions,
          deletedRequisitions,
          slackFeatures,
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset invitation");
    } finally {
      setResendingUserId(null);
    }
  };

  const handleDeleteUser = async (userId: string) => {
    setActionUserId(userId);

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/users/${userId}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${session.access_token}` }
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to delete user");
      }

      const deletedUser = users.find(u => u.id === userId);
      if (deletedUser && organization) {
        const newUsers = users.filter(u => u.id !== userId);
        const newDeleted = [...deletedUsers, { ...deletedUser, deleted_at: new Date().toISOString() }];
        setUsers(newUsers);
        setDeletedUsers(newDeleted);
        saveCache({
          organization,
          users: newUsers,
          deletedUsers: newDeleted,
          requisitions,
          deletedRequisitions,
          slackFeatures,
        });
      }

      setDeleteConfirmId(null);

    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete user");
    } finally {
      setActionUserId(null);
    }
  };

  const handleRestoreUser = async (userId: string) => {
    setActionUserId(userId);

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/users/${userId}/restore`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${session.access_token}` }
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to restore user");
      }

      const restoredUser = deletedUsers.find(u => u.id === userId);
      if (restoredUser && organization) {
        const newDeleted = deletedUsers.filter(u => u.id !== userId);
        const newUsers = [...users, { ...restoredUser, deleted_at: null }];
        setUsers(newUsers);
        setDeletedUsers(newDeleted);
        saveCache({
          organization,
          users: newUsers,
          deletedUsers: newDeleted,
          requisitions,
          deletedRequisitions,
          slackFeatures,
        });
      }

    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore user");
    } finally {
      setActionUserId(null);
    }
  };

  const handleAddRequisition = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newReqTitle.trim() || !newReqLocation.trim()) return;

    setAddingRequisition(true);
    setAddReqError("");

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/organizations/${orgId}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${session.access_token}`
        },
        body: JSON.stringify({
          role_title: newReqTitle.trim(),
          role_location: newReqLocation.trim(),
          experience_min_years: newReqMinYears,
          experience_max_years: noMaxYears ? null : newReqMaxYears
        })
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to create requisition");
      }

      const newReq = await response.json();

      setNewReqTitle("");
      setNewReqLocation("");
      setNewReqMinYears(0);
      setNewReqMaxYears(null);
      setNoMaxYears(false);
      setShowAddRequisition(false);

      router.push(`/requisitions/${newReq.id}/intake`);

    } catch (err) {
      setAddReqError(err instanceof Error ? err.message : "Failed to create requisition");
    } finally {
      setAddingRequisition(false);
    }
  };

  const handleDeleteRequisition = async (reqId: string) => {
    setActionReqId(reqId);

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${session.access_token}` }
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to delete requisition");
      }

      const deletedReq = requisitions.find(r => r.id === reqId);
      if (deletedReq && organization) {
        const newReqs = requisitions.filter(r => r.id !== reqId);
        const newDeleted = [...deletedRequisitions, deletedReq];
        setRequisitions(newReqs);
        setDeletedRequisitions(newDeleted);
        saveCache({
          organization,
          users,
          deletedUsers,
          requisitions: newReqs,
          deletedRequisitions: newDeleted,
          slackFeatures,
        });
      }

      setDeleteReqConfirmId(null);

    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete requisition");
    } finally {
      setActionReqId(null);
    }
  };

  const handleRestoreRequisition = async (reqId: string) => {
    setActionReqId(reqId);

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}/restore`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${session.access_token}` }
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to restore requisition");
      }

      const restoredReq = deletedRequisitions.find(r => r.id === reqId);
      if (restoredReq && organization) {
        const newDeleted = deletedRequisitions.filter(r => r.id !== reqId);
        const newReqs = [...requisitions, restoredReq];
        setRequisitions(newReqs);
        setDeletedRequisitions(newDeleted);
        saveCache({
          organization,
          users,
          deletedUsers,
          requisitions: newReqs,
          deletedRequisitions: newDeleted,
          slackFeatures,
        });
      }

    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore requisition");
    } finally {
      setActionReqId(null);
    }
  };

  const handleSlackFeatureToggle = async (feature: string, value: boolean) => {
    setSavingSlackFeatures(true);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/organizations/${orgId}/slack-features`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({ [feature]: value }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to update Slack features");
      }

      const updated = await response.json();
      if (updated.slack_features) {
        setSlackFeatures(updated.slack_features);
      } else {
        setSlackFeatures(prev => ({ ...prev, [feature]: value }));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setSavingSlackFeatures(false);
    }
  };

  const handleCalIntelToggle = async (field: string, value: boolean) => {
    setSavingCalIntel(true);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/organizations/${orgId}/calendar-intelligence`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({ [field]: value }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to update calendar intelligence settings");
      }

      const updated = await response.json();
      if (updated.auto_join_enabled !== undefined) {
        setAutoJoinEnabled(updated.auto_join_enabled);
      }
      if (updated.blocked_domains) {
        setBlockedDomains(updated.blocked_domains);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setSavingCalIntel(false);
    }
  };

  const handleUserFeatureToggle = async (userId: string, feature: string, value: boolean) => {
    setSavingUserFeatureId(userId);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/organizations/${orgId}/users/${userId}/slack-features`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({ [feature]: value }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to update user features");
      }

      const updated = await response.json();
      setUserFeatures(prev => ({
        ...prev,
        [userId]: updated.user_slack_features || null,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update user features");
    } finally {
      setSavingUserFeatureId(null);
    }
  };

  const getEffectiveFeature = (userId: string, feature: keyof SlackFeatures): { value: boolean; isOverride: boolean } => {
    const userOverride = userFeatures[userId];
    if (userOverride && feature in userOverride) {
      return { value: userOverride[feature], isOverride: true };
    }
    return { value: slackFeatures[feature], isOverride: false };
  };

  if (isLoading) {
    return (
      <AuthGuard>
        <div className="min-h-screen bg-secondary/30">
          <AdminNav />
          <main className="p-6">
            <div className="flex items-center gap-4 mb-6">
              <div className="p-2"><ArrowLeft className="w-5 h-5 text-muted-foreground" /></div>
              <div className="animate-pulse">
                <div className="h-7 bg-secondary rounded w-48 mb-2" />
                <div className="h-4 bg-secondary rounded w-32" />
              </div>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
              <div className="bg-card rounded-xl border border-border p-6">
                <DetailSkeleton />
              </div>
              <div className="lg:col-span-3 space-y-6">
                <div className="flex gap-4 border-b border-border pb-2">
                  <div className="h-8 bg-secondary rounded w-24 animate-pulse" />
                  <div className="h-8 bg-secondary rounded w-32 animate-pulse" />
                </div>
                <div className="bg-card rounded-xl border border-border p-6">
                  <div className="overflow-hidden rounded-lg border border-border">
                    <table className="w-full">
                      <thead className="bg-secondary/50">
                        <tr>
                          <th className="px-4 py-3 text-left"><div className="h-4 bg-secondary rounded w-16" /></th>
                          <th className="px-4 py-3 text-left"><div className="h-4 bg-secondary rounded w-16" /></th>
                          <th className="px-4 py-3 text-left"><div className="h-4 bg-secondary rounded w-16" /></th>
                          <th className="px-4 py-3 text-left"><div className="h-4 bg-secondary rounded w-16" /></th>
                          <th className="px-4 py-3 text-right"><div className="h-4 bg-secondary rounded w-16 ml-auto" /></th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {[1, 2, 3].map(i => <UserRowSkeleton key={i} />)}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          </main>
        </div>
      </AuthGuard>
    );
  }

  if (error || !organization) {
    return (
      <div id="org-detail-error" className="min-h-screen bg-secondary/30 flex items-center justify-center">
        <div className="text-center">
          <p className="text-muted-foreground mb-4">{error || "Organization not found"}</p>
          <Link href="/customers" className="text-primary hover:underline">Back to organizations</Link>
        </div>
      </div>
    );
  }

  return (
    <AuthGuard>
    <div id="organization-detail-page" className="min-h-screen bg-secondary/30">
      <AdminNav />

      <main className="p-6">
        <div className="flex items-center gap-4 mb-6">
          <Link id="org-detail-back-link" href="/customers" className="p-2 hover:bg-secondary rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <h1 id="org-detail-title" className="text-2xl font-bold">{organization.name}</h1>
              <button
                id="org-detail-refresh-btn"
                onClick={() => {
                  sessionStorage.removeItem(getCacheKey());
                  fetchData(true);
                }}
                disabled={isRefreshing}
                className="p-1.5 hover:bg-secondary rounded-lg transition-colors disabled:opacity-50"
                title="Refresh data"
              >
                {isRefreshing ? (
                  <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                ) : (
                  <RotateCcw className="w-4 h-4 text-muted-foreground" />
                )}
              </button>
            </div>
            {organization.domain && (
              <p className="text-muted-foreground">{organization.domain}</p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div id="org-detail-sidebar" className="bg-card rounded-xl border border-border p-6">
            <h2 id="org-details-heading" className="font-semibold mb-4">Organization Details</h2>
            <div className="space-y-4">
              <div id="org-detail-name">
                <p className="text-sm text-muted-foreground">Name</p>
                <p className="font-medium">{organization.name}</p>
              </div>
              {organization.domain && (
                <div id="org-detail-domain">
                  <p className="text-sm text-muted-foreground">Domain</p>
                  <p className="font-medium flex items-center gap-2">
                    <Globe className="w-4 h-4" />
                    {organization.domain}
                  </p>
                </div>
              )}
              {organization.description && (
                <div id="org-detail-description">
                  <p className="text-sm text-muted-foreground">Description</p>
                  <p className="font-medium">{organization.description}</p>
                </div>
              )}
              <div id="org-detail-created">
                <p className="text-sm text-muted-foreground">Created</p>
                <p className="font-medium">{new Date(organization.created_at).toLocaleDateString()}</p>
              </div>
            </div>

            <div id="org-slack-features" className="mt-6 pt-6 border-t border-border">
              <h3 className="font-semibold mb-1 flex items-center gap-2">
                Slack Features
                {savingSlackFeatures && <Loader2 className="w-3 h-3 animate-spin" />}
              </h3>
              <p className="text-xs text-muted-foreground mb-3">Org defaults — can be overridden per user in the Users tab</p>
              <div className="space-y-3">
                <label id="toggle-calendar-notifications" className="flex items-center justify-between cursor-pointer">
                  <div>
                    <p className="text-sm font-medium">Calendar Notifications</p>
                    <p className="text-xs text-muted-foreground">Interview detection alerts</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={slackFeatures.calendar_notifications}
                    onChange={(e) => handleSlackFeatureToggle("calendar_notifications", e.target.checked)}
                    disabled={savingSlackFeatures}
                    className="rounded border-border h-4 w-4"
                  />
                </label>
                <label id="toggle-assistant-read" className="flex items-center justify-between cursor-pointer">
                  <div>
                    <p className="text-sm font-medium">Assistant (Read)</p>
                    <p className="text-xs text-muted-foreground">Query roles, candidates, schedules</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={slackFeatures.assistant_read}
                    onChange={(e) => handleSlackFeatureToggle("assistant_read", e.target.checked)}
                    disabled={savingSlackFeatures}
                    className="rounded border-border h-4 w-4"
                  />
                </label>
                <label id="toggle-assistant-write" className="flex items-center justify-between cursor-pointer">
                  <div>
                    <p className="text-sm font-medium">Assistant (Write)</p>
                    <p className="text-xs text-muted-foreground">Schedule, create, update via Slack</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={slackFeatures.assistant_write}
                    onChange={(e) => handleSlackFeatureToggle("assistant_write", e.target.checked)}
                    disabled={savingSlackFeatures}
                    className="rounded border-border h-4 w-4"
                  />
                </label>
              </div>
            </div>

            <div id="org-calendar-intelligence" className="mt-6 pt-6 border-t border-border">
              <h3 className="font-semibold mb-3 flex items-center gap-2">
                Calendar Intelligence
                {savingCalIntel && <Loader2 className="w-3 h-3 animate-spin" />}
              </h3>
              <div className="space-y-3">
                <label id="toggle-auto-join" className="flex items-center justify-between cursor-pointer">
                  <div>
                    <p className="text-sm font-medium">Auto-Join Meetings</p>
                    <p className="text-xs text-muted-foreground">Automatically join detected interviews</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={autoJoinEnabled}
                    onChange={(e) => handleCalIntelToggle("auto_join_enabled", e.target.checked)}
                    disabled={savingCalIntel}
                    className="rounded border-border h-4 w-4"
                  />
                </label>
              </div>
            </div>
          </div>

          <div id="org-detail-main" className="lg:col-span-3 space-y-6">
            <div id="org-detail-tabs" className="flex gap-4 border-b border-border">
              <button
                id="org-tab-users"
                onClick={() => setActiveTab("users")}
                className={`flex items-center gap-2 px-4 py-2 border-b-2 transition-all duration-200 ${
                  activeTab === "users"
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                <Users className="w-4 h-4" />
                Users ({users.length})
              </button>
              <button
                id="org-tab-requisitions"
                onClick={() => setActiveTab("requisitions")}
                className={`flex items-center gap-2 px-4 py-2 border-b-2 transition-all duration-200 ${
                  activeTab === "requisitions"
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                <FileText className="w-4 h-4" />
                Requisitions ({requisitions.length})
              </button>
            </div>

            {activeTab === "users" && (
              <>
                <div id="org-users-section" className="bg-card rounded-xl border border-border p-6">
                  <div className="flex items-center justify-between mb-4">
                    <h2 id="org-users-heading" className="font-semibold">Active Users ({users.length})</h2>
                    <button
                      id="org-add-user-btn"
                      onClick={() => setShowAddUser(!showAddUser)}
                      className="flex items-center gap-2 px-3 py-1.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors text-sm"
                    >
                      <Plus className="w-4 h-4" />
                      Add User
                    </button>
                  </div>

                  {showAddUser && (
                    <form id="org-add-user-form" onSubmit={handleAddUser} className="mb-6 p-4 bg-secondary/50 rounded-lg animate-in slide-in-from-top duration-200">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                        <div>
                          <label htmlFor="org-new-user-name" className="block text-sm font-medium mb-1">Name</label>
                          <input
                            id="org-new-user-name"
                            type="text"
                            value={newUserName}
                            onChange={(e) => setNewUserName(e.target.value)}
                            placeholder="John Doe"
                            className="w-full px-3 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all"
                            required
                          />
                        </div>
                        <div>
                          <label htmlFor="org-new-user-email" className="block text-sm font-medium mb-1">Email</label>
                          <input
                            id="org-new-user-email"
                            type="email"
                            value={newUserEmail}
                            onChange={(e) => setNewUserEmail(e.target.value)}
                            placeholder="john@example.com"
                            className="w-full px-3 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all"
                            required
                          />
                        </div>
                      </div>
                      {addUserError && (
                        <p id="org-add-user-error" className="text-destructive text-sm mb-4">{addUserError}</p>
                      )}
                      <div className="flex justify-end gap-2">
                        <button
                          id="org-cancel-add-user"
                          type="button"
                          onClick={() => { setShowAddUser(false); setAddUserError(""); }}
                          className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors"
                        >
                          Cancel
                        </button>
                        <button
                          id="org-submit-add-user"
                          type="submit"
                          disabled={addingUser}
                          className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
                        >
                          {addingUser && <Loader2 className="w-4 h-4 animate-spin" />}
                          {addingUser ? "Sending invite..." : "Send Invite"}
                        </button>
                      </div>
                    </form>
                  )}

                  {users.length === 0 ? (
                    <div id="org-users-empty" className="text-center py-12 text-muted-foreground">
                      <Users className="w-12 h-12 mx-auto mb-3 opacity-50" />
                      <p>No active users in this organization</p>
                      <p className="text-sm">Add a user to send them a magic link invitation</p>
                    </div>
                  ) : (
                    <div id="org-users-table" className="overflow-hidden rounded-lg border border-border">
                      <table className="w-full">
                        <thead className="bg-secondary/50">
                          <tr>
                            <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Name</th>
                            <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Email</th>
                            <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Slack Access</th>
                            <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Added</th>
                            <th className="px-4 py-3 text-right text-sm font-medium text-muted-foreground">Actions</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                          {users.map(user => (
                            <tr key={user.id} id={`org-user-row-${user.id}`} className={`hover:bg-secondary/30 transition-colors ${actionUserId === user.id ? 'opacity-50' : ''}`}>
                              <td className="px-4 py-3">
                                <div className="flex items-center gap-3">
                                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                                    <span className="text-sm font-bold text-primary">
                                      {(user.full_name || user.email).charAt(0).toUpperCase()}
                                    </span>
                                  </div>
                                  <span className="font-medium">{user.full_name || "—"}</span>
                                </div>
                              </td>
                              <td className="px-4 py-3">
                                <div className="flex items-center gap-2 text-muted-foreground">
                                  <Mail className="w-4 h-4" />
                                  {user.email}
                                </div>
                              </td>
                              <td id={`user-slack-access-${user.id}`} className="px-4 py-3">
                                {Object.keys(userFeatures).length > 0 ? (
                                  <div className="space-y-1.5">
                                    <div className="flex items-center gap-3">
                                      {(["assistant_read", "assistant_write"] as const).map(feat => {
                                        const { value, isOverride } = getEffectiveFeature(user.id, feat);
                                        const label = feat === "assistant_read" ? "Read" : "Write";
                                        return (
                                          <label key={feat} className="flex items-center gap-1.5 cursor-pointer">
                                            <input
                                              id={`user-toggle-${feat}-${user.id}`}
                                              type="checkbox"
                                              checked={value}
                                              onChange={(e) => handleUserFeatureToggle(user.id, feat, e.target.checked)}
                                              disabled={savingUserFeatureId === user.id}
                                              className="rounded border-border h-3.5 w-3.5"
                                            />
                                            <span className={`text-xs ${isOverride ? "font-semibold text-primary" : "text-muted-foreground"}`}>
                                              {label}
                                            </span>
                                          </label>
                                        );
                                      })}
                                      {savingUserFeatureId === user.id && <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />}
                                    </div>
                                    {userFeatures[user.id] ? (
                                      <span className="text-[10px] text-primary font-medium">Override active</span>
                                    ) : (
                                      <span className="text-[10px] text-muted-foreground">Org default</span>
                                    )}
                                  </div>
                                ) : (
                                  <span className="text-xs text-muted-foreground">No Slack</span>
                                )}
                              </td>
                              <td className="px-4 py-3 text-muted-foreground text-sm">
                                {new Date(user.created_at).toLocaleDateString()}
                              </td>
                              <td className="px-4 py-3 text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <button
                                    id={`org-user-reset-btn-${user.id}`}
                                    onClick={() => handleResetInvite(user.id)}
                                    disabled={resendingUserId === user.id}
                                    className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950/30 rounded-lg transition-colors disabled:opacity-50"
                                    title="Reset account and send new magic link"
                                  >
                                    {resendingUserId === user.id ? (
                                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                    ) : (
                                      <RotateCcw className="w-3.5 h-3.5" />
                                    )}
                                    Reset
                                  </button>
                                  {deleteConfirmId === user.id ? (
                                    <div id={`org-user-delete-confirm-${user.id}`} className="flex items-center gap-2">
                                      <span className="text-sm text-muted-foreground">Delete?</span>
                                      <button
                                        id={`org-user-confirm-delete-${user.id}`}
                                        onClick={() => handleDeleteUser(user.id)}
                                        disabled={actionUserId === user.id}
                                        className="px-2 py-1 text-xs bg-destructive text-destructive-foreground rounded hover:bg-destructive/90 disabled:opacity-50 flex items-center gap-1"
                                      >
                                        {actionUserId === user.id ? <Loader2 className="w-3 h-3 animate-spin" /> : "Yes"}
                                      </button>
                                      <button
                                        id={`org-user-cancel-delete-${user.id}`}
                                        onClick={() => setDeleteConfirmId(null)}
                                        className="px-2 py-1 text-xs border border-border rounded hover:bg-secondary"
                                      >
                                        No
                                      </button>
                                    </div>
                                  ) : (
                                    <button
                                      id={`org-user-delete-btn-${user.id}`}
                                      onClick={() => setDeleteConfirmId(user.id)}
                                      className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
                                      title="Delete user"
                                    >
                                      <Trash2 className="w-4 h-4" />
                                    </button>
                                  )}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                {deletedUsers.length > 0 && (
                  <div id="org-deleted-users-section" className="bg-card rounded-xl border border-orange-200 dark:border-orange-900 p-6">
                    <div className="flex items-center gap-2 mb-4">
                      <AlertTriangle className="w-5 h-5 text-orange-500" />
                      <h2 id="org-deleted-users-heading" className="font-semibold text-orange-600 dark:text-orange-400">
                        Deleted Users ({deletedUsers.length})
                      </h2>
                    </div>
                    <p className="text-sm text-muted-foreground mb-4">
                      These users have been deleted and cannot log in.
                    </p>

                    <div id="org-deleted-users-table" className="overflow-hidden rounded-lg border border-border">
                      <table className="w-full">
                        <thead className="bg-orange-50 dark:bg-orange-950/30">
                          <tr>
                            <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Name</th>
                            <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Email</th>
                            <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Deleted</th>
                            <th className="px-4 py-3 text-right text-sm font-medium text-muted-foreground">Actions</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                          {deletedUsers.map(user => (
                            <tr key={user.id} id={`org-deleted-user-row-${user.id}`} className={`hover:bg-orange-50/50 dark:hover:bg-orange-950/20 transition-colors ${actionUserId === user.id ? 'opacity-50' : ''}`}>
                              <td className="px-4 py-3">
                                <div className="flex items-center gap-3">
                                  <div className="w-8 h-8 rounded-full bg-orange-100 dark:bg-orange-950 flex items-center justify-center">
                                    <span className="text-sm font-bold text-orange-600 dark:text-orange-400">
                                      {(user.full_name || user.email).charAt(0).toUpperCase()}
                                    </span>
                                  </div>
                                  <span className="font-medium text-muted-foreground">{user.full_name || "—"}</span>
                                </div>
                              </td>
                              <td className="px-4 py-3">
                                <div className="flex items-center gap-2 text-muted-foreground">
                                  <Mail className="w-4 h-4" />
                                  {user.email}
                                </div>
                              </td>
                              <td className="px-4 py-3 text-muted-foreground text-sm">
                                {user.deleted_at ? new Date(user.deleted_at).toLocaleDateString() : "—"}
                              </td>
                              <td className="px-4 py-3 text-right">
                                <button
                                  id={`org-user-restore-btn-${user.id}`}
                                  onClick={() => handleRestoreUser(user.id)}
                                  disabled={actionUserId === user.id}
                                  className="flex items-center gap-2 px-3 py-1.5 text-sm text-green-600 hover:bg-green-50 dark:hover:bg-green-950/30 rounded-lg transition-colors disabled:opacity-50 ml-auto"
                                >
                                  {actionUserId === user.id ? (
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                  ) : (
                                    <>
                                      <RotateCcw className="w-4 h-4" />
                                      Restore
                                    </>
                                  )}
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}

            {activeTab === "requisitions" && (
              <>
                <div id="org-requisitions-section" className="bg-card rounded-xl border border-border p-6">
                  <div className="flex items-center justify-between mb-4">
                    <h2 id="org-requisitions-heading" className="font-semibold">Active Requisitions ({requisitions.length})</h2>
                    <button
                      id="org-add-requisition-btn"
                      onClick={() => setShowAddRequisition(!showAddRequisition)}
                      className="flex items-center gap-2 px-3 py-1.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors text-sm"
                    >
                      <Plus className="w-4 h-4" />
                      New Requisition
                    </button>
                  </div>

                  {showAddRequisition && (
                    <form id="org-add-requisition-form" onSubmit={handleAddRequisition} className="mb-6 p-4 bg-secondary/50 rounded-lg animate-in slide-in-from-top duration-200">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                        <div>
                          <label htmlFor="org-new-req-title" className="block text-sm font-medium mb-1">Role Title *</label>
                          <input
                            id="org-new-req-title"
                            type="text"
                            value={newReqTitle}
                            onChange={(e) => setNewReqTitle(e.target.value)}
                            placeholder="Senior Software Engineer"
                            className="w-full px-3 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all"
                            required
                          />
                        </div>
                        <div>
                          <label htmlFor="org-new-req-location" className="block text-sm font-medium mb-1">Location *</label>
                          <input
                            id="org-new-req-location"
                            type="text"
                            value={newReqLocation}
                            onChange={(e) => setNewReqLocation(e.target.value)}
                            placeholder="San Francisco, CA"
                            className="w-full px-3 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all"
                            required
                          />
                        </div>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                        <div>
                          <label htmlFor="org-new-req-min-years" className="block text-sm font-medium mb-1">Min Years</label>
                          <input
                            id="org-new-req-min-years"
                            type="number"
                            min="0"
                            value={newReqMinYears}
                            onChange={(e) => setNewReqMinYears(parseInt(e.target.value) || 0)}
                            className="w-full px-3 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all"
                          />
                        </div>
                        <div>
                          <label htmlFor="org-new-req-max-years" className="block text-sm font-medium mb-1">Max Years</label>
                          <input
                            id="org-new-req-max-years"
                            type="number"
                            min="0"
                            value={newReqMaxYears ?? ""}
                            onChange={(e) => setNewReqMaxYears(e.target.value ? parseInt(e.target.value) : null)}
                            disabled={noMaxYears}
                            className="w-full px-3 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all disabled:opacity-50"
                          />
                        </div>
                        <div className="flex items-end pb-2">
                          <label className="flex items-center gap-2 cursor-pointer">
                            <input
                              id="org-new-req-no-max"
                              type="checkbox"
                              checked={noMaxYears}
                              onChange={(e) => {
                                setNoMaxYears(e.target.checked);
                                if (e.target.checked) setNewReqMaxYears(null);
                              }}
                              className="rounded border-border"
                            />
                            <span className="text-sm">No maximum (X+ years)</span>
                          </label>
                        </div>
                      </div>
                      {addReqError && (
                        <p id="org-add-req-error" className="text-destructive text-sm mb-4">{addReqError}</p>
                      )}
                      <div className="flex justify-end gap-2">
                        <button
                          id="org-cancel-add-req"
                          type="button"
                          onClick={() => { setShowAddRequisition(false); setAddReqError(""); }}
                          className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors"
                        >
                          Cancel
                        </button>
                        <button
                          id="org-submit-add-req"
                          type="submit"
                          disabled={addingRequisition}
                          className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
                        >
                          {addingRequisition && <Loader2 className="w-4 h-4 animate-spin" />}
                          {addingRequisition ? "Creating..." : "Create & Continue"}
                        </button>
                      </div>
                    </form>
                  )}

                  {requisitions.length === 0 ? (
                    <div id="org-requisitions-empty" className="text-center py-12 text-muted-foreground">
                      <FileText className="w-12 h-12 mx-auto mb-3 opacity-50" />
                      <p>No requisitions yet</p>
                      <p className="text-sm">Create a requisition to start the hiring process</p>
                    </div>
                  ) : (
                    <div id="org-requisitions-list" className="space-y-3">
                      {requisitions.map(req => (
                        <div key={req.id} id={`org-req-card-${req.id}`} className={`border border-border rounded-lg p-4 hover:bg-secondary/30 transition-all duration-200 ${actionReqId === req.id ? 'opacity-50' : ''}`}>
                          <div className="flex items-start justify-between">
                            <div className="flex-1">
                              <div className="flex items-center gap-3 mb-2">
                                <h3 className="font-semibold">{req.role_title}</h3>
                                <span className={`px-2 py-0.5 text-xs rounded-full ${
                                  req.status === "planned"
                                    ? "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400"
                                    : "bg-yellow-100 text-yellow-700 dark:bg-yellow-950 dark:text-yellow-400"
                                }`}>
                                  {req.status === "planned" ? "Planned" : "Intake Pending"}
                                </span>
                              </div>
                              <div className="flex items-center gap-4 text-sm text-muted-foreground">
                                <span className="flex items-center gap-1">
                                  <MapPin className="w-4 h-4" />
                                  {req.role_location}
                                </span>
                                <span className="flex items-center gap-1">
                                  <Briefcase className="w-4 h-4" />
                                  {req.experience_display}
                                </span>
                                <span className="flex items-center gap-1">
                                  <Clock className="w-4 h-4" />
                                  {new Date(req.created_at).toLocaleDateString()}
                                </span>
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              {req.status === "planned" && (
                                <Link
                                  id={`org-req-candidates-${req.id}`}
                                  href={`/requisitions/${req.id}/candidates`}
                                  className="flex items-center gap-1 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                                >
                                  <Users className="w-4 h-4" />
                                  Candidates
                                </Link>
                              )}
                              <Link
                                id={`org-req-edit-${req.id}`}
                                href={req.status === "planned" ? `/requisitions/${req.id}/plan/edit` : `/requisitions/${req.id}/intake`}
                                className="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-secondary transition-colors"
                              >
                                {req.status === "planned" ? "Edit Plan" : "Continue Setup"}
                              </Link>
                              {deleteReqConfirmId === req.id ? (
                                <div id={`org-req-delete-confirm-${req.id}`} className="flex items-center gap-2">
                                  <button
                                    id={`org-req-confirm-delete-${req.id}`}
                                    onClick={() => handleDeleteRequisition(req.id)}
                                    disabled={actionReqId === req.id}
                                    className="px-2 py-1 text-xs bg-destructive text-destructive-foreground rounded hover:bg-destructive/90 disabled:opacity-50 flex items-center gap-1"
                                  >
                                    {actionReqId === req.id ? <Loader2 className="w-3 h-3 animate-spin" /> : "Yes"}
                                  </button>
                                  <button
                                    id={`org-req-cancel-delete-${req.id}`}
                                    onClick={() => setDeleteReqConfirmId(null)}
                                    className="px-2 py-1 text-xs border border-border rounded hover:bg-secondary"
                                  >
                                    No
                                  </button>
                                </div>
                              ) : (
                                <button
                                  id={`org-req-delete-btn-${req.id}`}
                                  onClick={() => setDeleteReqConfirmId(req.id)}
                                  className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
                                  title="Delete requisition"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {deletedRequisitions.length > 0 && (
                  <div id="org-deleted-requisitions-section" className="bg-card rounded-xl border border-orange-200 dark:border-orange-900 p-6">
                    <div className="flex items-center gap-2 mb-4">
                      <AlertTriangle className="w-5 h-5 text-orange-500" />
                      <h2 id="org-deleted-reqs-heading" className="font-semibold text-orange-600 dark:text-orange-400">
                        Deleted Requisitions ({deletedRequisitions.length})
                      </h2>
                    </div>

                    <div id="org-deleted-requisitions-list" className="space-y-3">
                      {deletedRequisitions.map(req => (
                        <div key={req.id} id={`org-deleted-req-card-${req.id}`} className={`border border-orange-200 dark:border-orange-900 rounded-lg p-4 bg-orange-50/50 dark:bg-orange-950/20 transition-all duration-200 ${actionReqId === req.id ? 'opacity-50' : ''}`}>
                          <div className="flex items-start justify-between">
                            <div>
                              <h3 className="font-semibold text-muted-foreground">{req.role_title}</h3>
                              <div className="flex items-center gap-4 text-sm text-muted-foreground mt-1">
                                <span>{req.role_location}</span>
                                <span>{req.experience_display}</span>
                              </div>
                            </div>
                            <button
                              id={`org-req-restore-btn-${req.id}`}
                              onClick={() => handleRestoreRequisition(req.id)}
                              disabled={actionReqId === req.id}
                              className="flex items-center gap-2 px-3 py-1.5 text-sm text-green-600 hover:bg-green-50 dark:hover:bg-green-950/30 rounded-lg transition-colors disabled:opacity-50"
                            >
                              {actionReqId === req.id ? (
                                <Loader2 className="w-4 h-4 animate-spin" />
                              ) : (
                                <>
                                  <RotateCcw className="w-4 h-4" />
                                  Restore
                                </>
                              )}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </main>
    </div>
    </AuthGuard>
  );
}
