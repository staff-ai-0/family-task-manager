# Family Task Manager - Project Brief

**Project Name**: Family Task Manager  
**Model**: OurHome-inspired gamified family task organization  
**Target Audience**: Families with children (ages 6-14)  
**Created**: December 11, 2025  
**Last Updated**: December 12, 2025

## Executive Summary

Family Task Manager is a web application designed to help families organize daily tasks through gamification, rewards, and consequences. The system motivates children to complete their responsibilities by offering a point-based reward system while implementing gentle consequences for incomplete default tasks.

## Core Concept

The application divides tasks into two categories:

1. **Default Tasks (Obligatory)**: Must be completed to maintain access to privileges
   - Examples: homework, room cleaning, daily hygiene
   - Incomplete default tasks trigger consequences
   - Award fewer points (typically 10-50)

2. **Extra Tasks (Optional)**: Only accessible after default tasks are completed
   - Examples: help with dishes, organize closet, help siblings
   - Earn additional points for rewards
   - Award more points (typically 50-200)

## Business Model Inspiration: OurHome

We're following the proven OurHome model, which successfully combines:
- Family task organization
- Point-based reward system
- Gamification elements (badges, achievements)
- Parent-child collaboration
- Clean, intuitive interface

**Key OurHome Features to Replicate**:
1. Task assignment to specific family members
2. Points awarded upon completion
3. Customizable reward catalog
4. Progress tracking and achievements
5. Family-wide visibility of tasks and progress

## Problem We're Solving

**For Parents**:
- Difficulty motivating children to complete daily tasks
- Lack of visibility into completed vs pending tasks
- Inconsistent reward/consequence system
- Time spent managing tasks manually

**For Children**:
- Tasks feel like chores without clear rewards
- No visible progress tracking
- Unclear consequences for incomplete work
- Lack of motivation to do "extra" work

## Solution

A gamified task management system where:
- Tasks are visible and trackable
- Completion earns tangible points
- Points unlock rewards chosen by the family
- Default tasks must be completed to avoid restrictions
- Extra tasks provide bonus points for motivated children
- Parents have oversight and control

## Target Users

**Primary Users** (Children):
- Ages 6-14
- Need motivation for daily tasks
- Respond well to gamification
- Want visible progress and rewards

**Secondary Users** (Parents):
- Need task organization tools
- Want to motivate children positively
- Require oversight and control
- Desire consistency in enforcement

## Core Features

### Task Management
- Create default (obligatory) and extra (optional) tasks
- Assign tasks to specific children
- Set point values based on task difficulty
- Define frequency (daily, weekly, monthly)
- Track completion status

### Points & Rewards
- Earn points by completing tasks
- Redeem points for family-defined rewards
- Track point transactions
- Rewards catalog customized per family
- Parent approval for high-value rewards

### Consequence System
- Automatic consequences for incomplete default tasks
- Restrictions on screen time, rewards, or extra tasks
- Parent-controlled resolution
- Visible consequence status
- Time-based expiration

### Family Management
- Multiple family members
- Role-based access (Parent, Child, Teen)
- Shared task board
- Family-wide reward catalog
- Privacy between families

## Success Metrics

**User Engagement**:
- Daily active families
- Tasks completed per day
- Points redeemed per week
- Average session duration

**User Satisfaction**:
- Parent feedback on task completion rates
- Child engagement with extra tasks
- Reward redemption frequency
- Consequence resolution time

**System Health**:
- App uptime and performance
- Database query efficiency
- User-reported bugs
- Support requests

## Technical Requirements

**Must Have**:
- Fast, responsive web interface
- Mobile-friendly design
- Secure authentication
- Real-time updates (HTMX)
- PostgreSQL database
- Deployed on Render

**Nice to Have**:
- Push notifications for task reminders
- Parent mobile app
- Integration with screen time controls
- Export task history reports
- Multi-language support

## Competitive Analysis

| Application | Strengths | Weaknesses | Our Advantage |
|------------|-----------|------------|---------------|
| **OurHome** | Comprehensive features, proven model | Complex interface, many unused features | Simpler, focused on core task/reward flow |
| **Greenlight** | Financial integration | Too mature/financial focus | Age-appropriate gamification |
| **Cozi** | Calendar integration | Not reward-focused | Clear reward system with consequences |
| **Child Reward** | Simple star system | Too basic, no family management | Full family ecosystem |

## Revenue Model (Future)

**Phase 1** (Current): Free for all users
**Phase 2**: Freemium model
- Free: Basic task/reward system (1 family, 5 tasks/day)
- Premium ($5/month): Unlimited tasks, advanced analytics, custom rewards, priority support

**Phase 3**: Enterprise/School Edition
- Classroom task management
- School-wide point systems
- Parent-teacher coordination

## Roadmap

**MVP (Month 1-2)**:
- ✅ User authentication (email/password)
- ✅ Google OAuth integration
- ✅ Email verification system
- ✅ Password reset functionality
- ✅ Session-based authentication
- ✅ Role-based access control
- ✅ Task CRUD operations
- ✅ Points system
- ✅ Basic reward catalog
- ✅ Consequence tracking
- ✅ Family management

**Version 1.1 (Month 3)**:
- Push notifications
- Task templates
- Achievement badges
- Weekly reports
- Mobile optimization

**Version 1.2 (Month 4-5)**:
- Social features (share achievements)
- Recurring tasks automation
- Advanced analytics for parents
- Custom consequence rules

**Version 2.0 (Month 6+)**:
- Mobile apps (iOS/Android)
- Integration with parental control tools
- AI-suggested tasks based on age
- Multi-family support (for extended families)

## Design Principles

1. **Child-Friendly**: Colorful, engaging UI with icons and badges
2. **Parent-Controlled**: Clear oversight and control mechanisms
3. **Fair & Transparent**: Visible point transactions and task history
4. **Motivating**: Positive reinforcement over punishment
5. **Simple**: Easy to understand and use for all ages

## Success Criteria

**Month 1**: 10 active families, 80%+ task completion rate
**Month 3**: 50 active families, user satisfaction score 4.5/5
**Month 6**: 200 active families, 70%+ reward redemption rate
**Month 12**: 1000 active families, revenue positive

---

**Created**: December 11, 2025  
**Updated**: December 12, 2025  
**Current Phase**: MVP Complete - Authentication System Implemented
