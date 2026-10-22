import java.lang.instrument.Instrumentation;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

/** Read-only proof that exported caches belong to the actual business bean. */
public class NativeCertifyCacheBindingProbe {
    public static void agentmain(String argument, Instrumentation instrumentation) throws Exception {
        Path directory=Path.of(argument).toRealPath();
        if (!directory.toString().startsWith("/tmp/kdbt-private-cache-")) throw new SecurityException("Private probe directory required");
        Class<?> application=null;
        for (Class<?> type:instrumentation.getAllLoadedClasses())
            if (type.getName().equals("org.springframework.boot.SpringApplication")) application=type;
        if (application==null) throw new IllegalStateException("Retained application required");
        Object hook=null;
        for (Field field:application.getDeclaredFields())
            if (Modifier.isStatic(field.getModifiers()) && field.getType().getName().endsWith("SpringApplicationShutdownHook")) {
                field.setAccessible(true);hook=field.get(null);
            }
        if (hook==null) throw new IllegalStateException("Application contexts required");
        ClassLoader loader=application.getClassLoader();
        Class<?> managerType=Class.forName("org.springframework.cache.CacheManager",false,loader);
        Class<?> serviceType=Class.forName("io.mosip.certify.services.VCICacheService",false,loader);
        Set<Object> managers=Collections.newSetFromMap(new IdentityHashMap<>());
        Set<Object> services=Collections.newSetFromMap(new IdentityHashMap<>());
        for (Field field:hook.getClass().getDeclaredFields()) {
            if (!Collection.class.isAssignableFrom(field.getType())) continue;
            field.setAccessible(true);
            Object values=field.get(hook);if (!(values instanceof Collection<?>)) continue;
            for (Object context:new ArrayList<>((Collection<?>)values)) {
                try {
                    Method method=context.getClass().getMethod("getBeansOfType",Class.class);
                    managers.addAll(((Map<?,?>)method.invoke(context,managerType)).values());
                    services.addAll(((Map<?,?>)method.invoke(context,serviceType)).values());
                } catch (NoSuchMethodException ignored) { }
            }
        }
        if (managers.size()!=1 || services.size()!=1) throw new IllegalStateException("Unambiguous cache/business beans required");
        Object manager=managers.iterator().next(),service=services.iterator().next();
        Class<?> advised=Class.forName("org.springframework.aop.framework.Advised",false,loader);
        if (advised.isInstance(service)) {
            Object target=advised.getMethod("getTargetSource").invoke(service);
            Class<?> source=Class.forName("org.springframework.aop.TargetSource",false,loader);
            service=source.getMethod("getTarget").invoke(target);
        }
        Field injected=serviceType.getDeclaredField("cacheManager");injected.setAccessible(true);
        boolean matches=injected.get(service)==manager;
        Class<?> cacheType=Class.forName("org.springframework.cache.Cache",false,loader);
        List<String> types=new ArrayList<>();
        List<String> policies=new ArrayList<>();
        for (String name:List.of("credentialOfferCache","preAuthCodeCache","vcissuance")) {
            Object cache=managerType.getMethod("getCache",String.class).invoke(manager,name);
            Object map=cacheType.getMethod("getNativeCache").invoke(cache);
            types.add("\""+name+":"+cache.getClass().getName()+":"+map.getClass().getName()+"\"");
            if (map.getClass().getName().equals("com.google.common.cache.LocalCache")) {
                for (String property:List.of("expireAfterWriteNanos","expireAfterAccessNanos","keyEquivalence","valueEquivalence")) {
                    Field field=map.getClass().getDeclaredField(property);field.setAccessible(true);Object value=field.get(map);
                    policies.add("\""+name+":"+property+"="+(value instanceof Number?value:value.getClass().getName())+"\"");
                }
            }
        }
        Files.writeString(directory.resolve("cache-binding.json"),"{\"read_only\":true,\"registered_managers\":1,\"business_services\":1,\"business_cache_manager_identity_matches\":"+matches+",\"manager_class\":\""+manager.getClass().getName()+"\",\"business_cache_classes\":["+String.join(",",types)+"],\"cache_policies\":["+String.join(",",policies)+"]}",StandardOpenOption.CREATE_NEW);
    }
}
