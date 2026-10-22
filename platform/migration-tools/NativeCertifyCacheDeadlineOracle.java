import com.google.common.cache.CacheBuilder;
import java.util.*;
import java.util.concurrent.*;

/** Isolated executable checks against the retained Guava and Spring jars. */
public class NativeCertifyCacheDeadlineOracle {
    static int checks=0;
    static void check(boolean value) {if(!value)throw new AssertionError("Cache expiry oracle check "+(checks+1));checks++;}
    static Object manager(Map<Object,Object> values) throws Exception {
        Class<?> cache=Class.forName("org.springframework.cache.concurrent.ConcurrentMapCache");
        Object bean=cache.getConstructor(String.class,ConcurrentMap.class,boolean.class).newInstance("owned",values,true);
        Class<?> type=Class.forName("org.springframework.cache.support.SimpleCacheManager");Object manager=type.getConstructor().newInstance();
        type.getMethod("setCaches",Collection.class).invoke(manager,List.of(bean));type.getMethod("afterPropertiesSet").invoke(manager);return manager;
    }
    @SuppressWarnings("unchecked")
    static Map<Object,Object> wrapped(Object manager) throws Exception {
        Object cache=manager.getClass().getMethod("getCache",String.class).invoke(manager,"owned");
        Map<Object,Object> raw=(Map<Object,Object>)cache.getClass().getMethod("getNativeCache").invoke(cache);
        return NativeCertifyCacheDeadline.wrap(manager,"owned",cache,raw);
    }
    static void until(long deadline) throws Exception {Thread.sleep(Math.max(1,deadline-System.currentTimeMillis()+60));}
    public static void main(String[] args) throws Exception {
        ConcurrentMap<Object,Object> original=CacheBuilder.newBuilder().expireAfterWrite(900,TimeUnit.MILLISECONDS).build().asMap();
        original.put("legacy","value");long deadline=NativeCertifyCacheDeadline.capture(original,"legacy");
        check(deadline>System.currentTimeMillis());
        check(NativeCertifyCacheDeadline.capture(original,"legacy")==deadline);
        Thread.sleep(120);
        ConcurrentMap<Object,Object> fresh=CacheBuilder.newBuilder().expireAfterWrite(200,TimeUnit.MILLISECONDS).build().asMap();
        Object manager=manager(fresh);Map<Object,Object> restored=wrapped(manager);
        NativeCertifyCacheDeadline.restore(restored,"legacy","value",deadline);
        check(NativeCertifyCacheDeadline.capture(restored,"legacy")==deadline);
        check(restored.get("legacy").equals("value"));until(deadline);check(restored.get("legacy")==null);
        long nativeDeadline=System.currentTimeMillis()+2000;
        NativeCertifyCacheDeadline.restore(restored,"native","pending",nativeDeadline);
        Thread.sleep(350);check(restored.get("native").equals("pending"));
        check(NativeCertifyCacheDeadline.capture(restored,"native")==nativeDeadline);
        restored.put("ordinary","new");Thread.sleep(300);
        check(restored.get("ordinary")==null);check(restored.get("native").equals("pending"));
        restored.putIfAbsent("native","replacement");check(restored.get("native").equals("pending"));
        until(nativeDeadline);check(restored.get("native")==null);
        NativeCertifyCacheDeadline.restore(restored,"expired","never-revive",System.currentTimeMillis()-1);
        check(restored.get("expired")==null);
        NativeCertifyCacheDeadline.restore(restored,"unbounded","preserved",0);Thread.sleep(300);
        check(restored.get("unbounded").equals("preserved"));check(NativeCertifyCacheDeadline.capture(restored,"unbounded")==0);
        check(restored.replace("unbounded","preserved","ordinary-update"));Thread.sleep(300);check(restored.get("unbounded")==null);
        NativeCertifyCacheDeadline.restore(restored,"view","owned",System.currentTimeMillis()+5000);
        Iterator<Map.Entry<Object,Object>> view=restored.entrySet().iterator();check(view.next().getKey().equals("view"));view.remove();check(restored.isEmpty());
        NativeCertifyCacheDeadline.restore(restored,"view","owned",System.currentTimeMillis()+5000);
        restored.entrySet().iterator().next().setValue("updated");check(restored.get("view").equals("updated"));restored.clear();
        check(wrapped(manager)==restored);
        if(args.length>0) {
            ConcurrentMap<Object,Object> raw=CacheBuilder.newBuilder().expireAfterWrite(200,TimeUnit.MILLISECONDS).build().asMap();
            Object second=manager(raw),cache=second.getClass().getMethod("getCache",String.class).invoke(second,"owned");
            @SuppressWarnings("unchecked") Map<Object,Object> previous=(Map<Object,Object>)Class.forName(args[0])
                .getMethod("wrap",Object.class,String.class,Object.class,Map.class).invoke(null,second,"owned",cache,raw);
            long until=System.currentTimeMillis()+5000;
            NativeCertifyCacheDeadline.restore(previous,"previous-generation","owned",until);
            check(NativeCertifyCacheDeadline.capture(previous,"previous-generation")==until);
            check(wrapped(second)==previous);
        }
        System.out.println("{\"passed\":true,\"checks\":"+checks+",\"original_policy_for_new_writes_preserved\":true,\"absolute_recovered_expiry_preserved\":true}");
    }
}
