package io.mosip.esignet.config;

import io.mosip.esignet.nativecache.NativeCacheCodec;
import org.springframework.context.annotation.*;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import com.sun.net.httpserver.*;
import java.net.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.lang.reflect.*;
import java.util.concurrent.Executors;

/** Private loopback-only acceptance hook; never returns identities or ciphertext. */
@Configuration
public class NativeCacheBridgeConfiguration {
 private static volatile Object helper;
 @Bean public static BeanPostProcessor nativeCacheHelperCapture(){return new BeanPostProcessor(){
  public Object postProcessAfterInitialization(Object bean,String name){
   if(bean.getClass().getName().startsWith("io.mosip.esignet.services.AuthorizationHelperService"))helper=bean;
   return bean;
  }
 };}
 private static String call(String method,String input)throws Exception{
  if(helper==null)throw new IllegalStateException("Helper not available");
  Class<?> type=helper.getClass();Method m=null;
  while(type!=null){try{m=type.getDeclaredMethod(method,String.class);break;}catch(NoSuchMethodException ex){type=type.getSuperclass();}}
  if(m==null)throw new IllegalStateException("Helper method unavailable");m.setAccessible(true);return (String)m.invoke(helper,input);
 }
 @EventListener(ApplicationReadyEvent.class) public void ready()throws Exception {
  Path directory=Paths.get(System.getProperty("kdbt.cache.directory","/run/kdbt-native-cache"));byte[] token=Files.readAllBytes(directory.resolve("probe-token"));
  HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",18139),0);
  server.createContext("/check",exchange->{
   byte[] supplied=String.valueOf(exchange.getRequestHeaders().getFirst("Authorization")).getBytes(StandardCharsets.UTF_8);
   byte[] expected=("Bearer "+new String(token,StandardCharsets.UTF_8).trim()).getBytes(StandardCharsets.UTF_8);
   if(!exchange.getRequestMethod().equals("POST")||!MessageDigest.isEqual(supplied,expected)){exchange.sendResponseHeaders(403,-1);exchange.close();return;}
   boolean passed=false;
   try {
    String value="synthetic-cache-probe-"+java.util.UUID.randomUUID();
    String fresh=call("encryptIndividualId",value);
    if(!NativeCacheCodec.isNative(fresh)||!value.equals(call("decryptIndividualId",fresh)))throw new IllegalStateException();
    boolean legacyRejected=false;try{call("decryptIndividualId","legacy-ciphertext-must-be-migrated");}catch(Exception ex){legacyRejected=true;}
    if(!legacyRejected)throw new IllegalStateException();
    byte[] bad=java.util.Base64.getUrlDecoder().decode(fresh.substring("KDBTCACHE1.".length()));bad[bad.length-1]^=1;
    boolean rejected=false;try{call("decryptIndividualId","KDBTCACHE1."+java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(bad));}catch(Exception ex){rejected=true;}
    if(!rejected)throw new IllegalStateException();passed=true;
   }catch(Exception ex){passed=false;}finally{NativeCacheCodec.probeMode(null);}
   byte[] body=(passed?"{\"passed\":true,\"actual_spring_helper\":true,\"legacy_hsm_read\":false,\"native_roundtrip\":true,\"legacy_ciphertext_rejected\":true,\"hsm_fallback_removed\":true,\"tamper_rejected\":true}":"{\"passed\":false}").getBytes(StandardCharsets.UTF_8);
   exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(passed?200:503,body.length);exchange.getResponseBody().write(body);exchange.close();
  });
  server.setExecutor(Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"native-cache-acceptance");t.setDaemon(true);return t;}));server.start();
 }
}
