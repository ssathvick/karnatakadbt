package org.karnatakadbt.crypto;
import java.util.*;
import java.nio.file.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.type.TypeReference;
/** Keep the pinned original issuer JWKS published during signing-key rotation. */
public final class NativePublicTrust {
 public static Map<String,Object> merge(Map<String,Object> active){
  try{
   ObjectMapper json=new ObjectMapper();Map<String,Object> old=json.readValue(Files.readAllBytes(Paths.get("/run/kdbt-native-vault/retained-jwks.json")),new TypeReference<Map<String,Object>>(){});
   Map<String,Map<String,Object>> keys=new LinkedHashMap<>();
   for(Map<String,Object> source:new Map[]{active,old})for(Object item:(List<?>)source.getOrDefault("keys",Collections.emptyList())){
    Map<String,Object> key=(Map<String,Object>)item;if(key.containsKey("d")||key.containsKey("p")||key.containsKey("q")||!key.containsKey("kid"))throw new SecurityException("Public JWKS required");String id=(String)key.get("kid");
    if(keys.containsKey(id)){Map<String,Object> prior=keys.get(id);if(!Objects.equals(prior.get("n"),key.get("n"))||!Objects.equals(prior.get("e"),key.get("e")))throw new SecurityException("Conflicting key ID");}
    // The pinned historical bundle retains the original certificate validity.
    // Retiring a signing alias must not expire its published verification key.
    keys.put(id,new HashMap<>(key));
   }
   Map<String,Object> result=new HashMap<>(active);result.put("keys",new ArrayList<>(keys.values()));return result;
  }catch(Exception ex){throw new IllegalStateException("Native public trust bundle unavailable",ex);}
 }
}
