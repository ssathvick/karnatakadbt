import java.lang.instrument.Instrumentation;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.locks.Lock;

/** Pause the retained Spring executor through its supported lifecycle API.
 * Existing work drains. Managed executor queues remain; custom cron tasks are
 * cancelled and rebuilt from their retained runnable/trigger without backfill.
 * This is process-scoped, not a restart-proof admission mechanism.
 */
public class NativeCertifySchedulerAgent {
    static String owner;
    static final Set<Object> held = Collections.newSetFromMap(new IdentityHashMap<>());
    static final Map<Object, Object> heldTasks = new IdentityHashMap<>();
    static final Map<Object, Object> resumedTasks = new IdentityHashMap<>();
    static int httpBusy(Set<Object> executors) throws Exception {
        int count = 0;
        for (Object executor : executors) count += (int) executor.getClass().getMethod("getActiveCount").invoke(executor);
        return count;
    }
    public static synchronized void agentmain(String argument, Instrumentation instrumentation) throws Exception {
        Path directory = Path.of(argument).toRealPath();
        if (!directory.toString().matches("/tmp/kdbt-private-scheduler-[a-f0-9]{32}/[a-z0-9-]+"))
            throw new SecurityException("Private scheduler operation directory required");
        String command = Files.readString(directory.resolve("command")).strip();
        String operation = Files.readString(directory.resolve("operation")).strip();
        if (!operation.matches("[a-f0-9]{32}") || !Set.of("inspect", "pause", "resume", "gate-probe").contains(command))
            throw new SecurityException("Explicit bounded operation required");
        Class<?> app = null;
        for (Class<?> type : instrumentation.getAllLoadedClasses())
            if (type.getName().equals("org.springframework.boot.SpringApplication")) app = type;
        if (app == null) throw new IllegalStateException("No retained application");
        Object hook = null;
        for (Field field : app.getDeclaredFields())
            if (Modifier.isStatic(field.getModifiers()) && field.getType().getName().endsWith("SpringApplicationShutdownHook")) {
                field.setAccessible(true); hook = field.get(null);
            }
        if (hook == null) throw new IllegalStateException("No retained context");
        Set<Object> contexts = Collections.newSetFromMap(new IdentityHashMap<>());
        for (Field field : hook.getClass().getDeclaredFields()) {
            if (!Collection.class.isAssignableFrom(field.getType())) continue;
            field.setAccessible(true);
            if (field.get(hook) instanceof Collection<?> values) contexts.addAll(new ArrayList<>(values));
        }
        ClassLoader loader = app.getClassLoader();
        Set<Object> httpExecutors = Collections.newSetFromMap(new IdentityHashMap<>());
        for (Object context : contexts) {
            Method webServer;
            try { webServer = context.getClass().getMethod("getWebServer"); }
            catch (NoSuchMethodException ignored) { continue; }
            Object server = webServer.invoke(context);
            if (server == null) continue;
            Object tomcat = server.getClass().getMethod("getTomcat").invoke(server);
            Object service = tomcat.getClass().getMethod("getService").invoke(tomcat);
            for (Object connector : (Object[]) service.getClass().getMethod("findConnectors").invoke(service)) {
                Object protocol = connector.getClass().getMethod("getProtocolHandler").invoke(connector);
                Object executor = protocol.getClass().getMethod("getExecutor").invoke(protocol);
                if (!(executor instanceof ThreadPoolExecutor) && (executor == null ||
                    !executor.getClass().getName().equals("org.apache.tomcat.util.threads.ThreadPoolExecutor")))
                    throw new IllegalStateException("Unknown HTTP executor requires a separate drain adapter");
                httpExecutors.add(executor);
            }
        }
        if (httpExecutors.isEmpty()) throw new IllegalStateException("No observable retained HTTP executor");
        Class<?> schedulerType = Class.forName("org.springframework.scheduling.TaskScheduler", false, loader);
        Class<?> holderType = Class.forName("org.springframework.scheduling.config.ScheduledTaskHolder", false, loader);
        Class<?> poolType = Class.forName("org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler", false, loader);
        Class<?> supportType = poolType.getSuperclass();
        Class<?> taskExecutorType = Class.forName("org.springframework.core.task.TaskExecutor", false, loader);
        Set<Object> schedulers = Collections.newSetFromMap(new IdentityHashMap<>());
        Set<Object> executors = Collections.newSetFromMap(new IdentityHashMap<>());
        Set<Object> tasks = Collections.newSetFromMap(new IdentityHashMap<>());
        Map<Object, Object> customTasks = new IdentityHashMap<>();
        Set<ScheduledThreadPoolExecutor> customExecutors = Collections.newSetFromMap(new IdentityHashMap<>());
        Class<?> processorType = Class.forName("org.springframework.scheduling.annotation.ScheduledAnnotationBeanPostProcessor", false, loader);
        Class<?> registrarType = Class.forName("org.springframework.scheduling.config.ScheduledTaskRegistrar", false, loader);
        Class<?> scheduledTaskType = Class.forName("org.springframework.scheduling.config.ScheduledTask", false, loader);
        Class<?> triggerTaskType = Class.forName("org.springframework.scheduling.config.TriggerTask", false, loader);
        for (Object context : contexts) {
            Method beans;
            try { beans = context.getClass().getMethod("getBeansOfType", Class.class); }
            catch (NoSuchMethodException ignored) { continue; }
            schedulers.addAll(((Map<?, ?>) beans.invoke(context, schedulerType)).values());
            executors.addAll(((Map<?, ?>) beans.invoke(context, taskExecutorType)).values());
            for (Object holder : ((Map<?, ?>) beans.invoke(context, holderType)).values()) {
                Set<?> holderTasks = (Set<?>) holderType.getMethod("getScheduledTasks").invoke(holder);
                tasks.addAll(holderTasks);
                if (holderTasks.isEmpty()) continue;
                if (!processorType.isInstance(holder)) throw new IllegalStateException("Unknown task holder requires a separate adapter");
                Field registrarField = processorType.getDeclaredField("registrar"); registrarField.setAccessible(true);
                Object scheduler = registrarType.getMethod("getScheduler").invoke(registrarField.get(holder));
                if (poolType.isInstance(scheduler)) { schedulers.add(scheduler); continue; }
                if (scheduler == null || !scheduler.getClass().getName().equals("org.springframework.scheduling.concurrent.ConcurrentTaskScheduler"))
                    throw new IllegalStateException("Unknown actual task registrar scheduler");
                Field rawField = scheduler.getClass().getDeclaredField("scheduledExecutor"); rawField.setAccessible(true);
                Object raw = rawField.get(scheduler);
                if (!(raw instanceof ScheduledThreadPoolExecutor pool)) throw new IllegalStateException("Unsupported custom scheduled executor");
                customExecutors.add(pool);
                for (Object task : holderTasks) {
                    Object description = scheduledTaskType.getMethod("getTask").invoke(task);
                    if (!triggerTaskType.isInstance(description)) throw new IllegalStateException("Custom non-trigger task requires its own resume adapter");
                    customTasks.put(task, scheduler);
                }
            }
        }
        if (schedulers.isEmpty()) throw new IllegalStateException("No explicit observable scheduler; implicit scheduler needs separate adapter");
        for (Object scheduler : schedulers)
            if (!poolType.isInstance(scheduler)) throw new IllegalStateException("Unsupported scheduler type");
        executors.addAll(schedulers);
        for (Object executor : executors)
            if (!supportType.isInstance(executor)) throw new IllegalStateException("Unsupported asynchronous executor type");
        boolean gatePresent = false, gateTransformed = false, gateAllowed = false;
        long gateBlocked = 0;
        Class<?> gate = null;
        try {
            gate = Class.forName("NativeSchedulerGate", false, ClassLoader.getSystemClassLoader());
            gatePresent = true;
            gateTransformed = gate.getField("transformed").getBoolean(null);
            gateAllowed = (boolean) gate.getMethod("allow").invoke(null);
            gateBlocked = ((java.util.concurrent.atomic.AtomicLong) gate.getField("blocked").get(null)).get();
        } catch (ClassNotFoundException absent) { }
        if (command.equals("gate-probe")) {
            if (!gatePresent || !gateTransformed || gateAllowed || tasks.isEmpty())
                throw new SecurityException("Verified closed startup gate and actual scheduled task required");
            long before = gateBlocked;
            for (Object task : tasks) {
                Object description = scheduledTaskType.getMethod("getTask").invoke(task);
                Object runnable = description.getClass().getMethod("getRunnable").invoke(description);
                if (!runnable.getClass().getName().equals("org.springframework.scheduling.support.ScheduledMethodRunnable"))
                    throw new SecurityException("Only the pinned retained scheduled entry point may be probed");
                ((Runnable) runnable).run();
            }
            gateBlocked = ((java.util.concurrent.atomic.AtomicLong) gate.getField("blocked").get(null)).get();
            if (gateBlocked - before != tasks.size()) throw new IllegalStateException("Actual scheduled invocation bypassed startup admission");
        }
        if (command.equals("pause")) {
            if (owner != null && !owner.equals(operation)) throw new SecurityException("Scheduler owned by another operation");
            if (!resumedTasks.isEmpty()) throw new IllegalStateException("Finish the interrupted resume before another pause");
            owner = operation;
            Field futureField = scheduledTaskType.getDeclaredField("future"); futureField.setAccessible(true);
            for (Map.Entry<Object, Object> item : customTasks.entrySet()) {
                Object task = item.getKey();
                ScheduledFuture<?> future = (ScheduledFuture<?>) futureField.get(task);
                if (future == null || (future.isCancelled() && !heldTasks.containsKey(task)))
                    throw new IllegalStateException("Preexisting cancelled task must not be adopted");
                heldTasks.put(task, item.getValue());
                scheduledTaskType.getMethod("cancel", boolean.class).invoke(task, false);
            }
            for (Object scheduler : executors) {
                if (!(boolean) supportType.getMethod("isRunning").invoke(scheduler) && !held.contains(scheduler))
                    throw new IllegalStateException("Preexisting paused scheduler must not be adopted");
                held.add(scheduler); // Retain recovery ownership before stop, including timeout.
                CountDownLatch drained = new CountDownLatch(1);
                supportType.getMethod("stop", Runnable.class).invoke(scheduler, (Runnable) drained::countDown);
                if (!drained.await(25, TimeUnit.SECONDS)) throw new IllegalStateException("Scheduler drain timeout; pause retained");
            }
            int quiet = 0;
            for (int attempt = 0; attempt < 50 && quiet < 3; attempt++) {
                quiet = httpBusy(httpExecutors) == 0 ? quiet + 1 : 0;
                Thread.sleep(100);
            }
            if (quiet < 3) throw new IllegalStateException("Existing HTTP requests have not drained; pause retained");
            int customQuiet = 0;
            for (int attempt = 0; attempt < 200 && customQuiet < 3; attempt++) {
                customQuiet = customExecutors.stream().allMatch(e -> e.getActiveCount() == 0) ? customQuiet + 1 : 0;
                Thread.sleep(100);
            }
            if (customQuiet < 3) throw new IllegalStateException("Custom scheduled work has not drained; cancellation retained");
        } else if (command.equals("resume")) {
            Map<Object, Object> knownTasks = new IdentityHashMap<>(heldTasks); knownTasks.putAll(resumedTasks);
            if (!operation.equals(owner) || !held.equals(executors) || !knownTasks.equals(customTasks))
                throw new SecurityException("Exact scheduler ownership required");
            Field futureField = scheduledTaskType.getDeclaredField("future"); futureField.setAccessible(true);
            for (Map.Entry<Object, Object> item : new ArrayList<>(heldTasks.entrySet())) {
                if (!((ScheduledFuture<?>) futureField.get(item.getKey())).isCancelled())
                    throw new IllegalStateException("Unexpected live custom task; do not schedule a duplicate");
                Object description = scheduledTaskType.getMethod("getTask").invoke(item.getKey());
                Object runnable = description.getClass().getMethod("getRunnable").invoke(description);
                Object trigger = triggerTaskType.getMethod("getTrigger").invoke(description);
                Object future = schedulerType.getMethod("schedule", Runnable.class,
                    Class.forName("org.springframework.scheduling.Trigger", false, loader)).invoke(item.getValue(), runnable, trigger);
                if (!(future instanceof ScheduledFuture<?> scheduled)) throw new IllegalStateException("Custom task failed to resume");
                try { futureField.set(item.getKey(), future); }
                catch (Exception failure) { scheduled.cancel(false); throw failure; }
                resumedTasks.put(item.getKey(), item.getValue()); heldTasks.remove(item.getKey());
            }
            for (Object scheduler : held) supportType.getMethod("start").invoke(scheduler);
            held.clear(); resumedTasks.clear(); owner = null;
        }
        int running = 0, executing = 0, queued = 0;
        Field delegateField = supportType.getDeclaredField("lifecycleDelegate"); delegateField.setAccessible(true);
        for (Object scheduler : executors) {
            if ((boolean) supportType.getMethod("isRunning").invoke(scheduler)) running++;
            Object delegate = delegateField.get(scheduler);
            Field lockField = delegate.getClass().getDeclaredField("pauseLock"); lockField.setAccessible(true);
            Field countField = delegate.getClass().getDeclaredField("executingTaskCount"); countField.setAccessible(true);
            Lock lock = (Lock) lockField.get(delegate); lock.lock();
            try { executing += countField.getInt(delegate); } finally { lock.unlock(); }
            ThreadPoolExecutor executor = poolType.isInstance(scheduler)
                ? (ThreadPoolExecutor) poolType.getMethod("getScheduledThreadPoolExecutor").invoke(scheduler)
                : (ThreadPoolExecutor) scheduler.getClass().getMethod("getThreadPoolExecutor").invoke(scheduler);
            if (executor.isShutdown()) throw new IllegalStateException("Retained executor shut down");
            queued += executor.getQueue().size();
        }
        Files.writeString(directory.resolve("result.json"), "{\"schedulers\":" + schedulers.size() +
            ",\"executors\":" + executors.size() +
            ",\"http_executors\":" + httpExecutors.size() +
            ",\"http_executing\":" + httpBusy(httpExecutors) +
            ",\"custom_schedulers\":" + customExecutors.size() +
            ",\"custom_executing\":" + customExecutors.stream().mapToInt(ScheduledThreadPoolExecutor::getActiveCount).sum() +
            ",\"custom_paused_tasks\":" + heldTasks.size() +
            ",\"startup_gate_present\":" + gatePresent + ",\"startup_gate_transformed\":" + gateTransformed +
            ",\"startup_gate_allowed\":" + gateAllowed + ",\"startup_gate_blocked_calls\":" + gateBlocked +
            ",\"scheduled_tasks\":" + tasks.size() + ",\"running\":" + running + ",\"executing\":" + executing +
            ",\"queued\":" + queued + ",\"owned_pause\":" + operation.equals(owner) +
            ",\"process_scoped\":true}", StandardOpenOption.CREATE_NEW);
    }
}
